"""Parse the prices of a product page (/dp/<ASIN>), which the Subscribe & Save pages do not show.

A product page shows prices of many products: other variants, sponsored products and recommendations. Prices are only
read from blocks that belong to the product of the page (by its ASIN) and, for list prices, to the offer they are shown
for.
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import AlternativeOffer, ListPriceSource, ListPriceType
from amazon_subscriptions.parse import selectors
from amazon_subscriptions.parse.util import Html, attr_of, check_page, soup_of, text_of

logger = logging.getLogger(__name__)

#: ASINs in the links of a comparison widget entry
_LINK_ASIN_RE = re.compile(r"/(?:dp|gp/product|product-reviews)/([A-Z0-9]{10})\b|[?&]pd_rd_i=([A-Z0-9]{10})\b")
_ITEM_ID_PREFIX = "amzn1.asin."
_SELLER_ID_RE = re.compile(r"[?&]seller=([A-Z0-9]+)")


@dataclass(frozen=True)
class ProductPrices:
    """The prices of a product page. All ``None`` if the product is not available."""

    #: Price of a one-time purchase in the buybox.
    price: Decimal | None = None
    #: List price, if the page shows one for this product.
    list_price: Decimal | None = None
    #: What ``list_price`` is, by its label.
    list_price_type: ListPriceType | None = None
    #: The block ``list_price`` was read from.
    list_price_source: ListPriceSource | None = None
    #: Price per unit of measure of ``price``.
    unit_price: Decimal | None = None
    #: Unit of measure of ``unit_price``, e.g. ``l`` or ``Stück``.
    unit_price_unit: str | None = None
    #: The cheapest offer of another seller for the same product.
    alternative_offer: AlternativeOffer | None = None


@dataclass(frozen=True)
class _ListPrice:
    amount: Decimal
    type: ListPriceType
    source: ListPriceSource


def parse_product_page(html: Html, locale: SubscriptionLocale, page: str | None = None) -> ProductPrices:
    """The prices of the product of a product page: buybox price, list price, unit price and alternative offer."""
    soup = soup_of(html)
    check_page(soup, page)
    offers = soup.select(selectors.PRODUCT_OFFER)
    buybox = next((offer for offer in offers if not _is_alternative(offer, locale)), None)
    price = _offer_price(buybox, locale)
    if buybox is None or price is None:
        availability = text_of(soup.select_one(selectors.PRODUCT_AVAILABILITY))
        logger.debug(f"No price on the product page {page or ''}: {availability or 'no availability shown'}")
        return ProductPrices()

    asin = attr_of(buybox, "data-csa-c-asin")
    alternatives = [offer for offer in offers if _is_alternative(offer, locale) and _is_of(offer, asin)]
    unit_price = locale.parse_unit_price(text_of(buybox.select_one(selectors.PRODUCT_UNIT_PRICE)))
    list_price = (
        _display_list_price(soup, offers, buybox, locale, ListPriceSource.BUYBOX)
        or _widget_list_price(soup, asin, locale)
        or next(
            (
                found
                for offer in alternatives
                if (found := _display_list_price(soup, offers, offer, locale, ListPriceSource.ALTERNATIVE_OFFER))
            ),
            None,
        )
    )

    return ProductPrices(
        price=price,
        list_price=list_price.amount if list_price else None,
        list_price_type=list_price.type if list_price else None,
        list_price_source=list_price.source if list_price else None,
        unit_price=unit_price[0] if unit_price else None,
        unit_price_unit=unit_price[1] if unit_price else None,
        alternative_offer=_cheapest_alternative(alternatives, locale),
    )


def _offer_row(offer: Tag) -> Tag | None:
    """The buybox accordion row of an offer, ``None`` if the page has no accordion."""
    return offer.find_parent(id=re.compile(r"^newAccordionRow"))


def _is_alternative(offer: Tag, locale: SubscriptionLocale) -> bool:
    row = _offer_row(offer)
    return row is not None and locale.is_alternative_offers_caption(
        text_of(row.select_one(selectors.PRODUCT_OFFER_CAPTION))
    )


def _is_of(block: Tag, asin: str | None) -> bool:
    """Whether a block of the page is one of the product ``asin``. Blocks without ASIN belong to the page."""
    block_asin = attr_of(block, "data-csa-c-asin")
    return block_asin is None or block_asin == asin


def _offer_price(offer: Tag | None, locale: SubscriptionLocale) -> Decimal | None:
    return locale.parse_amount(text_of(offer.select_one(selectors.PRODUCT_PRICE))) if offer else None


def _display_list_price(
    soup: BeautifulSoup, offers: list[Tag], offer: Tag, locale: SubscriptionLocale, source: ListPriceSource
) -> _ListPrice | None:
    """The list price in the price display of an offer. Of an alternative offer, only a recommended retail price.

    The center column has one price display per offer, in the order of the offers, of which only the one of the
    selected offer is visible. A display is only used if it shows the price of its offer.
    """
    displays = soup.select(selectors.PRODUCT_PRICE_DISPLAY)
    if len(displays) != len(offers):
        logger.debug(f"{len(displays)} price displays for {len(offers)} offers, so no list price is read from them.")
        return None
    # Tags compare equal by their content, so the offer is found by identity
    display = displays[next(i for i, candidate in enumerate(offers) if candidate is offer)]
    shown = locale.parse_amount(text_of(display.select_one(selectors.PRODUCT_DISPLAY_PRICE), separator=""))
    price = _offer_price(offer, locale)
    if shown != price or not _is_of(display, attr_of(offer, "data-csa-c-asin")):
        logger.debug(f"The price display shows {shown} instead of the offer's {price}, so it is not used.")
        return None
    for basis in display.select(selectors.PRODUCT_BASIS_PRICE):
        list_price_type = locale.list_price_type_of(text_of(basis.select_one(selectors.PRODUCT_BASIS_PRICE_LABEL)))
        amount = locale.parse_amount(text_of(basis.select_one(selectors.PRODUCT_BASIS_PRICE_VALUE)))
        if list_price_type is None or amount is None:
            continue
        if source is ListPriceSource.BUYBOX or list_price_type is ListPriceType.UVP:
            return _ListPrice(amount, list_price_type, source)
    return None


def _widget_list_price(soup: BeautifulSoup, asin: str | None, locale: SubscriptionLocale) -> _ListPrice | None:
    """The recommended retail price of the entry of the product itself in a comparison widget.

    Only the recommended retail price is read: the entry may show another offer than the buybox, and other list
    prices belong to that offer.
    """
    if asin is None:
        return None
    for label in soup.select(f"{selectors.PRODUCT_WIDGET} {selectors.PRODUCT_WIDGET_LABEL}"):
        if not locale.is_this_item_label(text_of(label)):
            continue
        entry = label.find_parent(class_=selectors.PRODUCT_WIDGET_ENTRY)
        if entry is None or _widget_entry_asins(label, entry) != {asin}:
            continue
        for strike in entry.select(selectors.PRODUCT_WIDGET_STRIKE_PRICE):
            value = text_of(strike) or ""
            if locale.list_price_type_of((text_of(strike.parent) or "").replace(value, "")) is ListPriceType.UVP:
                amount = locale.parse_amount(value)
                if amount is not None:
                    return _ListPrice(amount, ListPriceType.UVP, ListPriceSource.WIDGET)
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


def _cheapest_alternative(alternatives: list[Tag], locale: SubscriptionLocale) -> AlternativeOffer | None:
    found = []
    for offer in alternatives:
        price = _offer_price(offer, locale)
        if price is None:
            continue
        unit_price = locale.parse_unit_price(text_of(offer.select_one(selectors.PRODUCT_UNIT_PRICE)))
        row = _offer_row(offer)
        seller_link = row.select_one(selectors.PRODUCT_OFFER_SELLER_LINK) if row else None
        seller_id = _SELLER_ID_RE.search(attr_of(seller_link, "href") or "")
        found.append(
            AlternativeOffer(
                price=price,
                unit_price=unit_price[0] if unit_price else None,
                unit_price_unit=unit_price[1] if unit_price else None,
                seller=text_of(row.select_one(selectors.PRODUCT_OFFER_SELLER)) if row else None,
                seller_id=seller_id.group(1) if seller_id else None,
            )
        )
    return min(found, key=lambda offer: offer.price, default=None)
