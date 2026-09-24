"""Parse the prices of a product page (/dp/<ASIN>), which the Subscribe & Save pages do not show."""

import logging
from dataclasses import dataclass
from decimal import Decimal

from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.parse import selectors
from amazon_subscriptions.parse.util import Html, check_page, soup_of, text_of

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductPrices:
    """The prices of a product page. All ``None`` if the product is not available."""

    #: Price of a one-time purchase.
    price: Decimal | None = None
    #: List price (RRP), if the page shows one.
    list_price: Decimal | None = None
    #: Price per unit of measure of ``price``.
    unit_price: Decimal | None = None
    #: Unit of measure of ``unit_price``, e.g. ``l`` or ``Stück``.
    unit_price_unit: str | None = None


def parse_product_page(html: Html, locale: SubscriptionLocale, page: str | None = None) -> ProductPrices:
    """The one-time purchase price, list price and unit price of a product page."""
    soup = soup_of(html)
    check_page(soup, page)
    offer = soup.select_one(selectors.PRODUCT_OFFER)
    price = locale.parse_amount(text_of(offer.select_one(selectors.PRODUCT_PRICE))) if offer else None
    if price is None:
        availability = text_of(soup.select_one(selectors.PRODUCT_AVAILABILITY))
        logger.debug(f"No price on the product page {page or ''}: {availability or 'no availability shown'}")
        return ProductPrices()

    unit_price = locale.parse_unit_price(text_of(offer.select_one(selectors.PRODUCT_UNIT_PRICE))) if offer else None

    # Without the list price label, the basis price is another price, e.g. the one-time price next to the S&S price.
    list_price = None
    for basis in soup.select(f"{selectors.PRODUCT_PRICE_DISPLAY} {selectors.PRODUCT_BASIS_PRICE}"):
        if locale.is_list_price_label(text_of(basis.select_one(selectors.PRODUCT_BASIS_PRICE_LABEL))):
            list_price = locale.parse_amount(text_of(basis.select_one(selectors.PRODUCT_BASIS_PRICE_VALUE)))
            break

    return ProductPrices(
        price=price,
        list_price=list_price,
        unit_price=unit_price[0] if unit_price else None,
        unit_price_unit=unit_price[1] if unit_price else None,
    )
