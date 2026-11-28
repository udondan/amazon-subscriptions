"""Read the recommended retail price of a product from the comparison widgets of its product page."""

import re
from collections.abc import Iterator
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import ListPriceType
from amazon_subscriptions.parse import selectors
from amazon_subscriptions.parse.util import attr_of, text_of

#: ASINs in the links of a comparison widget entry
_LINK_ASIN_RE = re.compile(r"/(?:dp|gp/product|product-reviews)/([A-Z0-9]{10})\b|[?&]pd_rd_i=([A-Z0-9]{10})\b")
_ITEM_ID_PREFIX = "amzn1.asin."


def widget_rrp(soup: BeautifulSoup, asin: str | None, locale: SubscriptionLocale) -> Decimal | None:
    """The recommended retail price of the entry of the product itself in a comparison widget.

    Only the recommended retail price is read: the entry may show another offer than the buybox, and other list
    prices belong to that offer.
    """
    if asin is None:
        return None
    for entry in _this_item_entries(soup, asin, locale):
        amount = _entry_rrp(entry, locale)
        if amount is not None:
            return amount
    return None


def _this_item_entries(soup: BeautifulSoup, asin: str, locale: SubscriptionLocale) -> Iterator[Tag]:
    """The widget entries labeled as this item that belong to the product with the ASIN."""
    for label in soup.select(f"{selectors.PRODUCT_WIDGET} {selectors.PRODUCT_WIDGET_LABEL}"):
        if not locale.is_this_item_label(text_of(label)):
            continue
        entry = label.find_parent(class_=selectors.PRODUCT_WIDGET_ENTRY)
        if entry is not None and _widget_entry_asins(label, entry) == {asin}:
            yield entry


def _entry_rrp(entry: Tag, locale: SubscriptionLocale) -> Decimal | None:
    """The first struck-through price of a widget entry that is labeled as recommended retail price."""
    for strike in entry.select(selectors.PRODUCT_WIDGET_STRIKE_PRICE):
        value = text_of(strike) or ""
        if locale.list_price_type_of((text_of(strike.parent) or "").replace(value, "")) is not ListPriceType.RRP:
            continue
        amount = locale.parse_amount(value)
        if amount is not None:
            return amount
    return None


def _widget_entry_asins(label: Tag, entry: Tag) -> set[str]:
    """The ASINs of a widget entry: of its item ID, or else of its links."""
    for parent in label.parents:
        item_id = attr_of(parent, "data-csa-c-item-id")
        if item_id and item_id.startswith(_ITEM_ID_PREFIX):
            return {item_id.removeprefix(_ITEM_ID_PREFIX)}
        if attr_of(parent, "data-feature-name"):
            break
    return {
        match.group(1) or match.group(2)
        for link in entry.select("a[href]")
        for match in _LINK_ASIN_RE.finditer(attr_of(link, "href") or "")
    }
