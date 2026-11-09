"""Read the Subscribe & Save pages with an authenticated :class:`~amazonauth.session.AmazonSession`.

The client is strictly read-only: :class:`~amazon_subscriptions.pages.PageLoader` checks every URL against
:data:`~amazon_subscriptions.pages.READ_ONLY_URLS` before it is requested, so links and forms that change
subscriptions (skip, pause, cancel, deliver now, ...) can never be requested, even if a page changes.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlencode

from amazonauth.constants import AuthConstants
from amazonauth.region_data import REGION_SITES
from amazonauth.session import AmazonSession
from bs4 import BeautifulSoup

from amazon_subscriptions.exceptions import (
    CaptchaError,
    PageStructureError,
    SessionExpiredError,
    SubscriptionsError,
)
from amazon_subscriptions.locales import get_locale, tld_of
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import ParseError, Subscription, UpcomingDelivery
from amazon_subscriptions.pages import LANDING_PATH, PageLoader, default_failed_dir
from amazon_subscriptions.parse import (
    BackupItem,
    apply_delivery_errors,
    match_deliveries,
    merge_delivery_card,
    parse_deliveries_next_url,
    parse_delivery_cards,
    parse_delivery_page,
    parse_product_page,
    parse_subscription_detail,
    parse_subscriptions,
    parse_subscriptions_next_url,
    selectors,
    set_substitute_asin,
)

__all__ = ["SubscriptionsClient", "default_failed_dir"]

logger = logging.getLogger(__name__)

DETAIL_PATH = "/auto-deliveries/ajax/subscription/"


@dataclass
class _Pages:
    """Everything loaded for one call, so both results come from the same state of the account."""

    subscriptions: list[Subscription]
    deliveries: list[UpcomingDelivery] = field(default_factory=list)


class SubscriptionsClient(PageLoader):
    """Read the Subscribe & Save subscriptions and upcoming deliveries of the session's account.

    :param session: A session of amazon-auth. Its cookies must hold a login (``amazon-subscriptions login``);
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
        super().__init__(session, max_pages, retry_delay, failed_dir)
        self.today = today or date.today()
        self.with_prices = with_prices
        self.locale: SubscriptionLocale = get_locale(self.base_url)
        self._check_english(session.config.constants)
        self._pages: _Pages | None = None

    def _check_english(self, constants: AuthConstants) -> None:
        """Check that amazon-auth requests the pages in English, the only language they are read in.

        :raises SubscriptionsError: If a ``constants_class`` requests another language.
        """
        site = REGION_SITES[tld_of(self.base_url)]
        if site.language_cookie and constants.REQUEST_COOKIES.get(site.language_cookie) != site.english_locale:
            raise SubscriptionsError(
                f"amazon-auth is configured to request the pages of {self.base_url} in another language than "
                f"English (cookie {site.language_cookie}={constants.REQUEST_COOKIES.get(site.language_cookie)!r}). "
                "Remove the constants_class from its configuration, only English pages can be read."
            )

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
        apply_delivery_errors(subscriptions, deliveries)
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
            deliveries.append(merge_delivery_card(card, delivery, url, errors))
        return deliveries

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
                if item.substitute and subscription is not None:
                    if subscription.subscription_id not in backups:
                        backups[subscription.subscription_id] = self._load_backup_item(subscription)
                    set_substitute_asin(item, backups[subscription.subscription_id], subscription, delivery)

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
