"""Request the Subscribe & Save pages with an authenticated :class:`~amazonauth.session.AmazonSession`.

Every URL is checked against :data:`READ_ONLY_URLS` before it is requested, so links and forms that change
subscriptions (skip, pause, cancel, deliver now, ...) can never be requested, even if a page changes.
"""

import dataclasses
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import TypeVar
from urllib.parse import urlencode, urljoin, urlparse

from amazonauth.session import AmazonSession
from bs4 import BeautifulSoup
from requests import RequestException, Response

from amazon_subscriptions.exceptions import (
    CaptchaError,
    PageStructureError,
    SessionExpiredError,
    SubscriptionsError,
)
from amazon_subscriptions.models import ParseError
from amazon_subscriptions.parse import AcpWidget, parse_acp_widget
from amazon_subscriptions.parse.util import Html

logger = logging.getLogger(__name__)

T = TypeVar("T")

LANDING_PATH = "/auto-deliveries"

#: The only URLs (path and query) that are requested. Everything else is refused with a
#: :class:`~amazon_subscriptions.exceptions.SubscriptionsError` before it is sent.
READ_ONLY_URLS = [
    # Landing page
    re.compile(r"/auto-deliveries/?"),
    # Delivery page, as linked by a delivery card
    re.compile(r"/auto-deliveries/?\?(?!.*ajax)(?=.*\bdeliveryDate=\d+).*"),
    # Detail sheet of a subscription, as opened by a subscription tile
    re.compile(r"/auto-deliveries/ajax/subscription/?\?(?=.*\bsubscriptionId=)[^#]*"),
    # Product page, only loaded with ``with_prices``
    re.compile(r"/dp/[A-Z0-9]{10}"),
    # Next page of the subscriptions and deliveries widgets of the landing page
    re.compile(r"/acp/myd-hub-(?:subscriptions|deliveries)-card-desktop/[^/?]+/paginate\?[^/]*"),
]
#: The only ``nextUrl`` values sent to the widgets, which request them on Amazon's side.
READ_ONLY_NEXT_URLS = re.compile(
    r"/api/marketplaces/[A-Z0-9]+/customer/replenishment/(?:subscriptions|fulfillment/deliveries)\?[^/]*"
)

#: The language segment that links of pages in another language than the storefront's start with, e.g. ``/-/en``.
LANGUAGE_PREFIX = re.compile(r"^(https://[^/]+)/-/[a-z]{2}(?:_[a-z]{2})?(?=/)", re.IGNORECASE)

#: Headers of the browser's XHR that loads the next page of a widget, on top of the session's base headers.
ACP_HEADERS = {
    "Accept": "text/html, application/json",
    "Content-Type": "application/json",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
    "x-amz-amabot-click-attributes": "disable",
}
#: Base headers of a page navigation, which the XHR does not send.
NAVIGATION_ONLY_HEADERS = ("Sec-Fetch-User", "Upgrade-Insecure-Requests")


def default_failed_dir() -> str:
    """``amazon-subscriptions/failed`` in the user's cache directory, where pages that could not be read are saved."""
    cache_dir = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(cache_dir, "amazon-subscriptions", "failed")


class PageLoader:
    """Load the read-only pages of the session's Amazon site, retry those that fail and save them for analysis.

    :param session: A session of amazon-auth with a login.
    :param max_pages: The maximum number of further pages loaded per widget, to never loop forever.
    :param retry_delay: Seconds to wait before loading a page a second time that could not be loaded or read.
    :param failed_dir: The directory where pages that could not be read are saved, defaults to
        :func:`default_failed_dir`.
    """

    def __init__(
        self, session: AmazonSession, max_pages: int, retry_delay: float, failed_dir: str | None = None
    ) -> None:
        self.session = session
        self.max_pages = max_pages
        self.retry_delay = retry_delay
        self.failed_dir = failed_dir or default_failed_dir()
        self.base_url: str = session.config.constants.BASE_URL.rstrip("/")
        #: The errors of all pages that could not be loaded or read, empty if the result is complete.
        self.errors: list[ParseError] = []
        #: The captcha of a delivery or product page, after which no further such pages are requested.
        self._captcha: CaptchaError | None = None

    def _paginate(
        self, landing: BeautifulSoup, next_page_selector: str, next_url_of: Callable[[Html], str | None], name: str
    ) -> Iterator[tuple[BeautifulSoup, str]]:
        """Yield the further pages of the widget of the landing page with the next page marker, as the browser
        loads them when scrolling."""
        widget = parse_acp_widget(landing, next_page_selector, LANDING_PATH)
        next_url = next_url_of(landing)
        seen: set[str] = set()
        while widget is not None and next_url:
            if next_url in seen:
                raise PageStructureError(f"The {name} pages repeat the next page {next_url!r}", LANDING_PATH)
            if len(seen) >= self.max_pages:
                raise SubscriptionsError(f"More than {self.max_pages} pages of {name}, stopped loading them.")
            seen.add(next_url)
            html, page = self._post_acp(widget, next_url, name)
            fragment = self._soup(html)
            yield fragment, page
            next_url = next_url_of(fragment)

    def _post_acp(self, widget: AcpWidget, next_url: str, name: str) -> tuple[str, str]:
        if not READ_ONLY_NEXT_URLS.fullmatch(next_url):
            raise SubscriptionsError(f"Refused to load the next page {next_url!r}, it is not a known read-only URL.")
        query = urlencode({"page-type": "RCXSubs", **widget.tracking, "stamp": widget.stamp})
        url = self._absolute(f"{widget.path.rstrip('/')}/paginate?{query}")
        self._check_read_only(url)

        base_headers = self.session.config.constants.BASE_HEADERS
        headers = {k: v for k, v in base_headers.items() if k not in NAVIGATION_ONLY_HEADERS}
        headers.update(ACP_HEADERS)
        headers.update(
            {
                "Origin": self.base_url,
                "Referer": self._absolute(LANDING_PATH),
                "x-amz-acp-params": widget.params,
            }
        )
        body = json.dumps({"nextUrl": next_url}, separators=(",", ":"))
        logger.debug(f"POST request: {url} {body}")
        # The session's post() would overwrite these headers with its base headers of a page navigation.
        response = self.session.session.post(
            url, headers=headers, data=body, timeout=self.session.config.request_timeout
        )
        html = self._text(response, url)
        page = self._write_debug_file(f"paginate-{name}", html) or url
        return html, page

    def _load_page(
        self, url: str, name: str, parse: Callable[[BeautifulSoup, str], T]
    ) -> tuple[T | None, list[ParseError]]:
        """Load and parse a page, and a second time after :attr:`retry_delay` if that fails.

        An attempt fails if the page cannot be loaded, the parser raises, or the result has ``parse_errors`` (e.g. a
        date taken from the URL). Every received page of a failed attempt is saved to :attr:`failed_dir`.

        :returns: The result of the first successful attempt and no errors. If both fail, the result of the second
            attempt (``None`` if it raised) and its errors, which are also added to :attr:`errors`.
        :raises SessionExpiredError: If the session has expired.
        :raises CaptchaError: If Amazon answers with a captcha, now or before. It is not retried.
        """
        result, errors = self._attempt(url, f"{name}_1", parse)
        if not errors:
            return result, []
        logger.info(f"Loading {url} again in {self.retry_delay} s: {errors[0].message}")
        time.sleep(self.retry_delay)
        result, errors = self._attempt(url, f"{name}_2", parse)
        for error in errors:
            self._error(error)
        return result, errors

    def _attempt(
        self, url: str, name: str, parse: Callable[[BeautifulSoup, str], T]
    ) -> tuple[T | None, list[ParseError]]:
        """Load and parse a page once, see :meth:`_load_page`. The page is saved if it fails."""
        self._raise_on_captcha()
        result: T | None = None
        html = None
        try:
            html = self._get(url)
            result = parse(self._soup(html), url)
            errors = list(getattr(result, "parse_errors", None) or [])
        except CaptchaError as e:
            self._captcha = e
            raise
        except SessionExpiredError:
            raise
        except (SubscriptionsError, RequestException) as e:
            result = None
            message = e.message if isinstance(e, PageStructureError) else str(e)
            errors = [ParseError(url=url, message=message, selector=getattr(e, "selector", None))]
        if errors:
            html_path = self._write_failed_file(name, html) if html is not None else None
            errors = [dataclasses.replace(error, html_path=html_path) for error in errors]
        return result, errors

    def _raise_on_captcha(self) -> None:
        if self._captcha is not None:
            raise self._captcha

    def _error(self, error: ParseError) -> ParseError:
        """Add an error to :attr:`errors`."""
        logger.debug(f"Error: {error}")
        self.errors.append(error)
        return error

    def _write_failed_file(self, name: str, text: str) -> str | None:
        """Save a page that could not be read, also without ``debug``, so its structure can be analyzed."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(self.failed_dir, f"{timestamp}_{name}.html")
        try:
            os.makedirs(self.failed_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            logger.warning(f"The page that could not be read was not saved to {path}: {e}")
            return None
        logger.debug(f"Page that could not be read written to file: {path}")
        return path

    def _get(self, url: str) -> str:
        self._check_read_only(url)
        return self._text(self.session.get(url).response, url)

    def _check_read_only(self, url: str) -> None:
        parsed = urlparse(url)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        if (
            f"{parsed.scheme}://{parsed.netloc}" != self.base_url
            or parsed.fragment
            or not any(pattern.fullmatch(path) for pattern in READ_ONLY_URLS)
        ):
            raise SubscriptionsError(f"Refused to request {url!r}, it is not a known read-only URL.")

    def _text(self, response: Response, url: str) -> str:
        if response.url.startswith(self.session.config.constants.SIGN_IN_URL):
            raise SessionExpiredError(f"Amazon redirected {url} to the sign-in page.")
        if not response.ok:
            raise SubscriptionsError(self.session.build_response_error(response))
        # Amazon sends the fragments without charset, where requests would fall back to ISO-8859-1.
        charset = response.encoding if "charset" in response.headers.get("Content-Type", "").lower() else None
        return response.content.decode(charset or "utf-8", errors="replace")

    def _soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, self.session.config.bs4_parser)

    def _write_debug_file(self, name: str, text: str) -> str | None:
        """Write a response the session did not write itself, as it does for its own requests with ``debug``."""
        if not self.session.debug:
            return None
        output_dir = self.session.config.output_dir
        os.makedirs(output_dir, exist_ok=True)
        index = 0
        while os.path.exists(path := os.path.join(output_dir, f"{name}_{index}.html")):
            index += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.debug(f"Response written to file: {path}")
        return path

    def _absolute(self, url: str) -> str:
        """The absolute URL of a link, without the language prefix of English pages (``/-/en/auto-deliveries``),
        as the language cookie already requests them in English."""
        return LANGUAGE_PREFIX.sub(r"\1", urljoin(self.base_url + "/", url), count=1)
