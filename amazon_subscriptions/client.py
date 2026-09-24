"""Load the Subscribe & Save pages with an authenticated :class:`~amazonorders.session.AmazonSession`.

The client is strictly read-only: every URL is checked against :data:`READ_ONLY_URLS` before it is requested, so
links and forms that change subscriptions (skip, pause, cancel, deliver now, ...) can never be requested, even if a
page changes.
"""

import dataclasses
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TypeVar
from urllib.parse import urlencode, urljoin, urlparse

from amazonorders.session import AmazonSession
from bs4 import BeautifulSoup
from requests import RequestException, Response

from amazon_subscriptions.exceptions import (
    CaptchaError,
    PageStructureError,
    SessionExpiredError,
    SubscriptionsError,
)
from amazon_subscriptions.locales import get_locale
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import DiscountTier, ParseError, Subscription, UpcomingDelivery
from amazon_subscriptions.parse import (
    AcpWidget,
    BackupItem,
    match_deliveries,
    parse_acp_widget,
    parse_deliveries_next_url,
    parse_delivery_cards,
    parse_delivery_page,
    parse_product_page,
    parse_subscription_detail,
    parse_subscriptions,
    parse_subscriptions_next_url,
    selectors,
    titles_match,
)
from amazon_subscriptions.parse.util import Html

logger = logging.getLogger(__name__)

T = TypeVar("T")

LANDING_PATH = "/auto-deliveries"
DETAIL_PATH = "/auto-deliveries/ajax/subscription/"

#: The only URLs (path and query) the client requests. Everything else is refused with a
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


@dataclass
class _Pages:
    """Everything loaded for one call, so both results come from the same state of the account."""

    subscriptions: list[Subscription]
    deliveries: list[UpcomingDelivery] = field(default_factory=list)


class SubscriptionsClient:
    """Read the Subscribe & Save subscriptions and upcoming deliveries of the session's account.

    :param session: A session of amazon-orders. Its cookies must hold a login (``amazon-subscriptions login``);
        the client never logs in by itself.
    :param today: The date to resolve dates rendered without year, defaults to today.
    :param max_pages: The maximum number of further pages loaded per widget, to never loop forever.
    :param with_prices: Also load the product page of each subscription for its regular price, list price and unit
        price, which the Subscribe & Save pages do not show. One more request per subscription.
    :param retry_delay: Seconds to wait before loading a delivery or product page a second time that could not be
        loaded or read.
    :param failed_dir: The directory where delivery and product pages that could not be read are saved, defaults
        to :func:`default_failed_dir`.

    A delivery or product page that still fails the second time does not fail the call: the delivery or
    subscription is returned with what is known from the other pages, and the error is added to its
    ``parse_errors`` and to :attr:`errors`. Only the overview (landing page and its further pages) and an expired
    session are fatal.
    """

    def __init__(
        self,
        session: AmazonSession,
        today: date | None = None,
        max_pages: int = 20,
        with_prices: bool = False,
        retry_delay: float = 2.0,
        failed_dir: str | None = None,
    ) -> None:
        self.session = session
        self.today = today or date.today()
        self.max_pages = max_pages
        self.with_prices = with_prices
        self.retry_delay = retry_delay
        self.failed_dir = failed_dir or default_failed_dir()
        self.base_url: str = session.config.constants.BASE_URL.rstrip("/")
        self.locale: SubscriptionLocale = get_locale(self.base_url)
        #: The errors of all pages that could not be loaded or read, empty if the result is complete.
        self.errors: list[ParseError] = []
        self._pages: _Pages | None = None
        #: The captcha of a delivery or product page, after which no further such pages are requested.
        self._captcha: CaptchaError | None = None

    def get_subscriptions(self) -> list[Subscription]:
        """All subscriptions, with their next delivery and its price if Amazon shows it."""
        return self._load().subscriptions

    def get_upcoming_deliveries(self) -> list[UpcomingDelivery]:
        """The upcoming deliveries with their items, linked to the subscriptions."""
        return self._load().deliveries

    def _load(self) -> _Pages:
        if self._pages is not None:
            return self._pages
        if not self.session.auth_cookies_stored():
            raise SessionExpiredError("There is no stored Amazon session.")

        landing_url = self._absolute(LANDING_PATH)
        landing = self._soup(self._get(landing_url))
        subscriptions = self._load_subscriptions(landing, landing_url)
        deliveries = self._load_deliveries(self._load_delivery_cards(landing, landing_url))
        match_deliveries(subscriptions, deliveries)
        for delivery in deliveries:
            # The next delivery of these subscriptions, and so their price, may be incomplete.
            for subscription in subscriptions:
                if delivery.parse_errors and subscription.next_delivery_date == delivery.date:
                    subscription.parse_errors += delivery.parse_errors
        self._load_substitutes(subscriptions, deliveries)
        if self.with_prices:
            self._load_prices(subscriptions)
        self._pages = _Pages(subscriptions, deliveries)
        return self._pages

    def _load_subscriptions(self, landing: BeautifulSoup, landing_url: str) -> list[Subscription]:
        subscriptions = parse_subscriptions(landing, self.locale, self.today, landing_url)
        for fragment, page in self._paginate(
            landing, selectors.SUBSCRIPTIONS_NEXT_PAGE, parse_subscriptions_next_url, "subscriptions"
        ):
            subscriptions += parse_subscriptions(fragment, self.locale, self.today, page)

        ids = [s.subscription_id for s in subscriptions]
        if len(set(ids)) != len(ids):
            raise PageStructureError("The subscription pages repeat subscriptions", landing_url)
        for subscription in subscriptions:
            if subscription.product_url:
                subscription.product_url = self._absolute(subscription.product_url)
        return subscriptions

    def _load_delivery_cards(self, landing: BeautifulSoup, landing_url: str) -> list[UpcomingDelivery]:
        cards = parse_delivery_cards(landing, self.locale, landing_url)
        for fragment, page in self._paginate(
            landing, selectors.DELIVERIES_NEXT_PAGE, parse_deliveries_next_url, "deliveries"
        ):
            cards += parse_delivery_cards(fragment, self.locale, page, fragment=True)
        return cards

    def _load_deliveries(self, cards: list[UpcomingDelivery]) -> list[UpcomingDelivery]:
        """The delivery pages of the cards. A captcha stops loading them, as every further request would get one too;
        the remaining deliveries are then the cards."""
        deliveries = []
        for card in cards:
            if not card.url:
                raise PageStructureError(f"Delivery card of {card.date} without link", LANDING_PATH)
            url = self._absolute(card.url)
            try:
                delivery, errors = self._load_page(
                    url, f"delivery-{card.date}", lambda soup, page: parse_delivery_page(soup, self.locale, page)
                )
            except CaptchaError as e:
                delivery, errors = None, [self._error(ParseError(url=url, message=str(e)))]
            deliveries.append(self._merge_delivery(card, delivery, url, errors))
        return deliveries

    def _merge_delivery(
        self, card: UpcomingDelivery, delivery: UpcomingDelivery | None, url: str, errors: list[ParseError]
    ) -> UpcomingDelivery:
        """The delivery of a delivery page with the card's link and bundle, or the card if its page failed."""
        if delivery is None:
            return UpcomingDelivery(
                date=card.date,
                change_deadline=card.change_deadline,
                discount_tier=DiscountTier(item_count=card.discount_tier.item_count),
                currency=card.currency,
                delivery_bundle_id=card.delivery_bundle_id,
                url=url,
                parse_errors=errors,
            )
        delivery.parse_errors = errors
        if delivery.date != card.date:
            logger.warning(f"The delivery card shows {card.date}, but its page shows {delivery.date}.")
        if delivery.discount_tier.item_count is None:
            delivery.discount_tier.item_count = card.discount_tier.item_count
        delivery.change_deadline = delivery.change_deadline or card.change_deadline
        delivery.delivery_bundle_id = card.delivery_bundle_id
        delivery.url = url
        return delivery

    def _load_substitutes(self, subscriptions: list[Subscription], deliveries: list[UpcomingDelivery]) -> None:
        """Set the ASIN of the backup products sent instead of subscribed ones.

        Delivery pages show no ASINs, so the detail sheet of the subscription is loaded, which names its backup
        product. It is only used if its title matches the item's title.
        """
        by_id = {s.subscription_id: s for s in subscriptions}
        backups: dict[str, BackupItem | None] = {}
        for delivery in deliveries:
            for item in delivery.items:
                subscription = by_id.get(item.subscription_id or "")
                if not item.substitute or subscription is None:
                    continue
                if subscription.subscription_id not in backups:
                    backups[subscription.subscription_id] = self._load_backup_item(subscription)
                backup = backups[subscription.subscription_id]
                if backup is not None and titles_match(backup.title, item.title):
                    item.substitute_asin = backup.asin
                else:
                    logger.warning(
                        f"The backup product of subscription {subscription.subscription_id} is not the item "
                        f"{item.title!r} of {delivery.date}, so its ASIN is not known."
                    )

    def _load_backup_item(self, subscription: Subscription) -> BackupItem | None:
        query = {"subscriptionId": subscription.subscription_id, "enableMydExperience": "1", "clientName": "mydHub"}
        if subscription.asin:
            query["subAsin"] = subscription.asin
        url = self._absolute(f"{DETAIL_PATH}?{urlencode(query)}")
        try:
            self._raise_on_captcha()
            return parse_subscription_detail(self._soup(self._get(url)), url)
        except SessionExpiredError:
            raise
        except SubscriptionsError as e:
            if isinstance(e, CaptchaError):
                self._captcha = e
            logger.warning(f"The detail sheet of subscription {subscription.subscription_id} was not loaded: {e}")
            return None

    def _load_prices(self, subscriptions: list[Subscription]) -> None:
        """Set the prices of the product pages of the subscriptions.

        A product page that fails leaves the prices of its subscription ``None`` and adds the error to its
        ``parse_errors``. A captcha stops loading them, as every further request would get one too.
        """
        for subscription in subscriptions:
            if not subscription.asin:
                continue
            url = self._absolute(f"/dp/{subscription.asin}")
            try:
                prices, errors = self._load_page(
                    url, f"product-{subscription.asin}", lambda soup, page: parse_product_page(soup, self.locale, page)
                )
            except CaptchaError as e:
                subscription.parse_errors.append(self._error(ParseError(url=url, message=str(e))))
                logger.debug(f"Stopped loading the product pages for their prices: {e}")
                return
            subscription.parse_errors += errors
            if prices is None:
                continue
            subscription.price = prices.price
            subscription.list_price = prices.list_price
            subscription.list_price_type = prices.list_price_type
            subscription.list_price_source = prices.list_price_source
            subscription.unit_price = prices.unit_price
            subscription.unit_price_unit = prices.unit_price_unit
            subscription.alternative_offer = prices.alternative_offer

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
        result: T | None = None
        errors: list[ParseError] = []
        for attempt in (1, 2):
            if attempt == 2:
                logger.info(f"Loading {url} again in {self.retry_delay} s: {errors[0].message}")
                time.sleep(self.retry_delay)
            self._raise_on_captcha()
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
            if not errors:
                return result, []
            html_path = self._write_failed_file(f"{name}_{attempt}", html) if html is not None else None
            errors = [dataclasses.replace(error, html_path=html_path) for error in errors]
        for error in errors:
            self._error(error)
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
        return urljoin(self.base_url + "/", url)
