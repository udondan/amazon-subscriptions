"""Parse the delivery cards of the landing page and the delivery pages."""

import json
import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from bs4 import Tag

from amazon_subscriptions import dates
from amazon_subscriptions.exceptions import PageStructureError
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import DeliveryItem, DiscountTier, ParseError, UpcomingDelivery
from amazon_subscriptions.parse import selectors
from amazon_subscriptions.parse.util import Html, attr_of, check_page, soup_of, text_of

logger = logging.getLogger(__name__)


def parse_delivery_cards(
    html: Html, locale: SubscriptionLocale, page: str | None = None, fragment: bool = False
) -> list[UpcomingDelivery]:
    """Parse the delivery cards of the landing page, without items. Their ``url`` leads to the delivery page.

    :param fragment: ``True`` for a fragment returned by the pagination of the deliveries widget. It is empty
        (``<div></div>``) if there are no further deliveries, else it must have cards. The landing page must have the
        widget, but may have no cards.
    :raises PageStructureError: If the landing page has no deliveries widget, a fragment with content has no cards,
        or a card has no date.
    """
    soup = soup_of(html)
    check_page(soup, page)
    cards = soup.select(selectors.DELIVERY_CARD)
    if fragment and not cards and not soup.get_text(strip=True) and not soup.find(["img", "a", "span"]):
        return []
    if fragment and not cards:
        raise PageStructureError(
            f"No delivery cards found ({selectors.DELIVERY_CARD!r})", page, selector=selectors.DELIVERY_CARD
        )
    if not fragment and soup.select_one(selectors.DELIVERIES_WIDGET) is None:
        raise PageStructureError(
            f"No deliveries found ({selectors.DELIVERIES_WIDGET!r})", page, selector=selectors.DELIVERIES_WIDGET
        )
    return [_parse_card(card, locale, page) for card in cards]


def parse_deliveries_next_url(html: Html) -> str | None:
    """The URL of the next page of the deliveries widget, if there is one."""
    return attr_of(soup_of(html).select_one(selectors.DELIVERIES_NEXT_PAGE), "data-next-url")


def _parse_card(card: Tag, locale: SubscriptionLocale, page: str | None) -> UpcomingDelivery:
    url = attr_of(card.select_one(selectors.DELIVERY_CARD_LINK), "href")
    query = parse_qs(urlparse(url or "").query)
    epoch_ms = _delivery_date_param(url)
    arrival = deadline = None
    for text in (text_of(tag) for tag in card.select("span")):
        if text and text.startswith(locale.ARRIVAL_PREFIX):
            arrival = locale.parse_date_parts(text)
        elif text and text.startswith(locale.DEADLINE_PREFIX):
            deadline = locale.parse_date_parts(text)
    if arrival is None or not epoch_ms.isdigit():
        raise PageStructureError(f"Delivery card without arrival date or link: {url!r}", page)

    # The timestamp is midnight of the storefront's time zone, so its UTC date may be the day before. It is only
    # used to find the year of the rendered date.
    reference = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc).date()
    delivery_date = dates.resolve(arrival, lambda d, m: dates.nearest(d, m, reference))
    if delivery_date is None:
        raise PageStructureError(f"Delivery card with invalid arrival date: {url!r}", page)

    images = len(card.select(selectors.DELIVERY_CARD_IMAGE))
    more = re.sub(r"\D", "", text_of(card.select_one(selectors.DELIVERY_CARD_MORE_ITEMS)) or "")
    return UpcomingDelivery(
        date=delivery_date,
        change_deadline=dates.resolve(deadline, lambda d, m: dates.last_on_or_before(d, m, delivery_date)),
        discount_tier=DiscountTier(item_count=images + int(more or 0) if images else None),
        currency=locale.CURRENCY,
        delivery_bundle_id=next(iter(query.get("deliveryBundleId", [])), None),
        url=url,
    )


def parse_delivery_page(html: Html, locale: SubscriptionLocale, page: str | None = None) -> UpcomingDelivery:
    """Parse a delivery page with its items.

    Items are not linked to subscriptions yet, see :func:`amazon_subscriptions.parse.matching.match_deliveries`.

    If the page shows no delivery date, it is taken from the ``deliveryDate`` of the page URL ``page``, and the missing
    date is noted in ``parse_errors`` of the delivery.

    :raises PageStructureError: If neither the page nor its URL has a delivery date, or the page has no items.
    """
    soup = soup_of(html)
    check_page(soup, page)
    parse_errors = []
    delivery_date = _parse_delivery_date(text_of(soup.select_one(selectors.DELIVERY_DATE)))
    if delivery_date is None:
        delivery_date = _date_of_epoch_ms(_delivery_date_param(page), locale.TIMEZONE)
        if delivery_date is None:
            raise PageStructureError(
                f"No delivery date found ({selectors.DELIVERY_DATE!r})", page, selector=selectors.DELIVERY_DATE
            )
        logger.debug(f"The delivery page shows no delivery date, so it was taken from its URL: {delivery_date}")
        parse_errors.append(
            ParseError(
                url=page,
                message="No delivery date found, it was taken from the URL",
                selector=selectors.DELIVERY_DATE,
            )
        )

    item_tags = soup.select(selectors.DELIVERY_ITEM)
    if not item_tags:
        raise PageStructureError(
            f"No delivery items found ({selectors.DELIVERY_ITEM!r})", page, selector=selectors.DELIVERY_ITEM
        )
    items = [_parse_item(tag, locale) for tag in item_tags]

    item_count = locale.parse_item_count(text_of(soup.select_one(selectors.DELIVERY_ITEM_COUNT)))
    if item_count is not None and item_count != len(items):
        logger.warning(f"Delivery of {delivery_date} states {item_count} items, but {len(items)} were found.")
    savings_text = text_of(soup.select_one(selectors.DELIVERY_SAVINGS))
    deadline = locale.parse_date_parts(text_of(soup.select_one(selectors.DELIVERY_EDIT_DEADLINE)))

    prices = [item.price for item in items]
    return UpcomingDelivery(
        date=delivery_date,
        change_deadline=dates.resolve(deadline, lambda d, m: dates.last_on_or_before(d, m, delivery_date)),
        items=items,
        discount_tier=DiscountTier(
            item_count=item_count if item_count is not None else len(items),
            max_discount_unlocked=(
                locale.MAX_DISCOUNT_UNLOCKED_TEXT.lower() in savings_text.lower() if savings_text else None
            ),
            savings=locale.parse_savings(savings_text),
        ),
        total=sum((p for p in prices if p is not None), Decimal("0")) if None not in prices else None,
        currency=locale.CURRENCY,
        parse_errors=parse_errors,
    )


def _delivery_date_param(url: str | None) -> str:
    """The ``deliveryDate`` of a delivery link, a timestamp in milliseconds, or ``""``."""
    return (parse_qs(urlparse(url or "").query).get("deliveryDate") or [""])[0]


def _date_of_epoch_ms(epoch_ms: str, time_zone: str) -> date | None:
    """The date of a timestamp in milliseconds in the storefront's time zone, where it is midnight."""
    if not epoch_ms.isdigit():
        return None
    return datetime.fromtimestamp(int(epoch_ms) / 1000, tz=ZoneInfo(time_zone)).date()


def _parse_delivery_date(text: str | None) -> date | None:
    """The date of ``{"value":{"dateTime":"2026-10-01T00:00:00.000+02:00","zoneId":"Europe/Paris"}}``."""
    try:
        value = json.loads(text or "")["value"]["dateTime"]
        # The local date of the storefront, not converted to UTC
        return date.fromisoformat(value[:10])
    except (ValueError, KeyError, TypeError):
        logger.debug(f"Delivery date {text!r} was not recognized, so it was not parsed.")
        return None


def _item_container(tag: Tag) -> Tag:
    """The largest element around an item tile that holds no other item, which also holds the item's alert."""
    container = tag
    while container.parent is not None and len(container.parent.select(selectors.DELIVERY_ITEM)) == 1:
        container = container.parent
    return container


def _parse_item(tag: Tag, locale: SubscriptionLocale) -> DeliveryItem:
    price_tag = tag.select_one(selectors.DELIVERY_ITEM_PRICE)
    price_text = None
    if price_tag is not None:
        labelled = price_tag.select_one("[aria-label]")
        price_text = attr_of(labelled, "aria-label") or text_of(price_tag, separator="")
    alert = text_of(_item_container(tag).select_one(selectors.DELIVERY_ITEM_ALERT))
    quantity_interval_text = text_of(tag.select_one(selectors.DELIVERY_ITEM_QUANTITY_INTERVAL))
    quantity_interval = locale.parse_quantity_interval(quantity_interval_text)
    return DeliveryItem(
        title=text_of(tag.select_one(selectors.DELIVERY_ITEM_TITLE)) or "",
        quantity=quantity_interval[0] if quantity_interval else None,
        interval=quantity_interval[1] if quantity_interval else None,
        price=locale.parse_amount(price_text),
        discount_percent=locale.parse_discount_percent(text_of(tag.select_one(selectors.DELIVERY_ITEM_DISCOUNT))),
        alert_text=alert,
        substitute=bool(alert and locale.is_substitute_alert(alert)),
    )
