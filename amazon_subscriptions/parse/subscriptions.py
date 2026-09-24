"""Parse the subscription tiles of the landing page and of its paginated grid fragments."""

import logging
from datetime import date
from urllib.parse import parse_qs, urlparse

from bs4 import Tag

from amazon_subscriptions import dates
from amazon_subscriptions.exceptions import PageStructureError
from amazon_subscriptions.locales.base import SubscriptionLocale, normalize_space
from amazon_subscriptions.models import Subscription, SubscriptionStatus
from amazon_subscriptions.parse import selectors
from amazon_subscriptions.parse.util import Html, attr_of, check_page, soup_of, text_of

logger = logging.getLogger(__name__)


def parse_subscriptions(
    html: Html, locale: SubscriptionLocale, today: date, page: str | None = None
) -> list[Subscription]:
    """Parse the subscriptions of the landing page or of a fragment of its paginated grid.

    :param html: The landing page, or a fragment returned by the grid's pagination.
    :param locale: The locale of the storefront.
    :param today: The date the page was loaded, to resolve dates rendered without year.
    :param page: Name of the page for error messages (e.g. the debug file).
    :raises PageStructureError: If the page has no subscriptions and does not say so.
    """
    soup = soup_of(html)
    check_page(soup, page)
    tiles = soup.select(selectors.SUBSCRIPTION_TILE)
    if not tiles:
        if locale.NO_SUBSCRIPTIONS_TEXT and locale.NO_SUBSCRIPTIONS_TEXT in soup.get_text(" "):
            return []
        raise PageStructureError(f"No subscriptions found ({selectors.SUBSCRIPTION_TILE!r})", page)
    return [_parse_tile(tile, locale, today, page) for tile in tiles]


def parse_subscriptions_next_url(html: Html) -> str | None:
    """The URL of the next page of the subscriptions grid, if there is one."""
    return attr_of(soup_of(html).select_one(selectors.SUBSCRIPTIONS_NEXT_PAGE), "data-next-url")


def _parse_tile(tile: Tag, locale: SubscriptionLocale, today: date, page: str | None) -> Subscription:
    edit_url = attr_of(tile, "data-edit-url") or ""
    query = parse_qs(urlparse(edit_url).query)
    subscription_id = next(iter(query.get("subscriptionId", [])), None)
    if not subscription_id:
        raise PageStructureError(f"Subscription tile without subscription id: {edit_url!r}", page)
    asin = next(iter(query.get("subAsin", [])), None)

    title_tag = tile.select_one(selectors.SUBSCRIPTION_TILE_TITLE)
    image = tile.select_one(selectors.SUBSCRIPTION_TILE_IMAGE)
    subscription = Subscription(
        subscription_id=subscription_id,
        asin=asin,
        title=text_of(title_tag) or attr_of(image, "alt"),
        product_url=f"/dp/{asin}" if asin else None,
        image_url=attr_of(image, "src"),
        currency=locale.CURRENCY,
    )

    status_texts = []
    for string in tile.find_all(string=True):
        text = normalize_space(string)
        if not text or any(parent is title_tag for parent in string.parents):
            continue
        if text.startswith(locale.NEXT_DELIVERY_PREFIX):
            subscription.next_delivery_date = dates.resolve(
                locale.parse_date_parts(text), lambda d, m: dates.next_delivery(d, m, today)
            )
        elif (quantity_interval := locale.parse_quantity_interval(text, warn=False)) is not None:
            subscription.quantity, subscription.interval = quantity_interval
        elif text not in locale.TILE_ACTION_TEXTS:
            status_texts.append(text)

    if status_texts:
        subscription.raw_status_text = " | ".join(status_texts)
        subscription.status = locale.status_of(status_texts[0])
    elif subscription.next_delivery_date is not None:
        subscription.status = SubscriptionStatus.ACTIVE
    if subscription.quantity is None:
        logger.warning(f"Subscription {subscription_id} has no quantity and interval.")
    return subscription
