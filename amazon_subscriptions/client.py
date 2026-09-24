"""Load the Subscribe & Save pages with an authenticated :class:`~amazonorders.session.AmazonSession`.

The client is strictly read-only: every URL is checked against :data:`READ_ONLY_URLS` before it is requested, so
links and forms that change subscriptions (skip, pause, cancel, deliver now, ...) can never be requested, even if a
page changes.
"""

import json
import logging
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlencode, urljoin, urlparse

from amazonorders.session import AmazonSession
from bs4 import BeautifulSoup
from requests import Response

from amazon_subscriptions.exceptions import (
    CaptchaError,
    PageStructureError,
    SessionExpiredError,
    SubscriptionsError,
)
from amazon_subscriptions.locales import get_locale
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import Subscription, UpcomingDelivery
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
    """

    def __init__(
        self, session: AmazonSession, today: date | None = None, max_pages: int = 20, with_prices: bool = False
    ) -> None:
        self.session = session
        self.today = today or date.today()
        self.max_pages = max_pages
        self.with_prices = with_prices
        self.base_url: str = session.config.constants.BASE_URL.rstrip("/")
        self.locale: SubscriptionLocale = get_locale(self.base_url)
        self._pages: _Pages | None = None

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
        deliveries = [self._load_delivery(card) for card in self._load_delivery_cards(landing, landing_url)]
        match_deliveries(subscriptions, deliveries)
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

    def _load_delivery(self, card: UpcomingDelivery) -> UpcomingDelivery:
        """The delivery page of a card, with the card's link and bundle."""
        if not card.url:
            raise PageStructureError(f"Delivery card of {card.date} without link", LANDING_PATH)
        url = self._absolute(card.url)
        delivery = parse_delivery_page(self._soup(self._get(url)), self.locale, url)
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
            html = self._get(url)
        except (SessionExpiredError, CaptchaError):
            raise
        except SubscriptionsError as e:
            logger.warning(f"The detail sheet of subscription {subscription.subscription_id} was not loaded: {e}")
            return None
        return parse_subscription_detail(self._soup(html), url)

    def _load_prices(self, subscriptions: list[Subscription]) -> None:
        """Set the prices of the product pages of the subscriptions.

        A product page that fails leaves the prices of its subscription ``None``. A captcha stops loading them, as
        every further request would get one too.
        """
        for subscription in subscriptions:
            if not subscription.asin:
                continue
            url = self._absolute(f"/dp/{subscription.asin}")
            try:
                prices = parse_product_page(self._soup(self._get(url)), self.locale, url)
            except CaptchaError as e:
                logger.warning(f"Stopped loading the product pages for their prices: {e}")
                return
            except SessionExpiredError:
                raise
            except SubscriptionsError as e:
                logger.warning(f"The product page of {subscription.asin} was not loaded: {e}")
                continue
            subscription.price = prices.price
            subscription.list_price = prices.list_price
            subscription.unit_price = prices.unit_price
            subscription.unit_price_unit = prices.unit_price_unit

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
