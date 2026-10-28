import re
from decimal import Decimal

import pytest

from amazon_subscriptions.exceptions import CaptchaError
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import ListPriceSource, ListPriceType
from amazon_subscriptions.parse import ProductPrices, parse_product_page
from amazon_subscriptions.serialize import to_json
from tests.conftest import FIXTURES, read_fixture


def display_label(label: str) -> str:
    """The label of the list price in the price display of an offer."""
    return f'apex-basisprice-label">{label}<'


#: The label of the list price in the entry "This item:" of the comparison widget
WIDGET_LABEL = "<span>Was:</span>"
#: Texts of the page around the seller name, which are never one
SELLER_UI_TEXT_RE = re.compile(r"more information|details|seller|ships from|see more", re.IGNORECASE)


def test_product_with_rrp(de: SubscriptionLocale) -> None:
    prices = parse_product_page(read_fixture("de/product-rrp.html"), de)
    assert prices == ProductPrices(
        price=Decimal("8.69"),
        list_price=Decimal("11.99"),
        list_price_type=ListPriceType.RRP,
        list_price_source=ListPriceSource.BUYBOX,
        unit_price=Decimal("57.93"),
        unit_price_unit="l",
    )


def test_product_with_was_price(de: SubscriptionLocale) -> None:
    prices = parse_product_page(read_fixture("de/product-was.html"), de)
    assert prices == ProductPrices(
        price=Decimal("6.13"),
        list_price=Decimal("6.45"),
        list_price_type=ListPriceType.WAS,
        list_price_source=ListPriceSource.BUYBOX,
        unit_price=Decimal("52.62"),
        unit_price_unit="kg",
    )


@pytest.mark.parametrize(("label", "expected"), [("Was:", ListPriceType.WAS), ("RRP:", ListPriceType.RRP)])
def test_product_list_price_type(de: SubscriptionLocale, label: str, expected: ListPriceType) -> None:
    html = read_fixture("de/product-rrp.html").replace(display_label("RRP:"), display_label(label))
    prices = parse_product_page(html, de)
    assert (prices.list_price, prices.list_price_type, prices.list_price_source) == (
        Decimal("11.99"),
        expected,
        ListPriceSource.BUYBOX,
    )


def test_product_list_price_unknown_label(de: SubscriptionLocale) -> None:
    html = read_fixture("de/product-rrp.html").replace(display_label("RRP:"), display_label("Formerly:"))
    prices = parse_product_page(html, de)
    assert (prices.price, prices.list_price, prices.list_price_type) == (Decimal("8.69"), None, None)


def test_product_price_display_of_another_price(de: SubscriptionLocale) -> None:
    # A price display that does not show the price of its offer belongs to something else
    html = read_fixture("de/product-rrp.html").replace('a-price-whole">8<', 'a-price-whole">9<', 1)
    prices = parse_product_page(html, de)
    assert (prices.price, prices.list_price) == (Decimal("8.69"), None)


def test_product_list_price_of_the_widget(de: SubscriptionLocale) -> None:
    # Without a list price in the price display, the recommended retail price of the entry "This item:" is used
    html = (
        read_fixture("de/product-was.html")
        .replace(display_label("Was:"), display_label("Formerly:"))
        .replace(WIDGET_LABEL, "<span>RRP:</span>")
    )
    prices = parse_product_page(html, de)
    assert (prices.price, prices.list_price, prices.list_price_type, prices.list_price_source) == (
        Decimal("6.13"),
        Decimal("6.45"),
        ListPriceType.RRP,
        ListPriceSource.WIDGET,
    )


def test_product_other_list_price_of_the_widget(de: SubscriptionLocale) -> None:
    # The widget entry may show another offer than the buybox, so only its recommended retail price is used
    html = read_fixture("de/product-was.html").replace(display_label("Was:"), display_label("Formerly:"))
    prices = parse_product_page(html, de)
    assert (prices.price, prices.list_price, prices.list_price_source) == (Decimal("6.13"), None, None)


def test_product(de: SubscriptionLocale) -> None:
    # The label "One-Time Price:" of the price display is no list price
    prices = parse_product_page(read_fixture("de/product.html"), de)
    assert prices == ProductPrices(price=Decimal("12.99"), unit_price=Decimal("133.92"), unit_price_unit="kg")


def test_product_single_offer(de: SubscriptionLocale) -> None:
    # A page without buybox accordion
    prices = parse_product_page(read_fixture("de/product-single-offer.html"), de)
    assert prices == ProductPrices(price=Decimal("56.48"), unit_price=Decimal("9.41"), unit_price_unit="count")


def test_product_no_foreign_prices(de: SubscriptionLocale) -> None:
    html = read_fixture("de/product.html")
    # The page shows prices of a sponsored product and of the products of the comparison widget
    foreign = sorted(set(re.findall(r'a-price-whole">(\d+)<', html)) - {"12"})
    assert foreign
    prices = parse_product_page(html, de)
    serialized = to_json(prices)
    assert all(f'"{whole}.' not in serialized for whole in foreign)


@pytest.mark.parametrize("fixture", sorted(path.name for path in (FIXTURES / "de").glob("product*.html")))
def test_product_seller_is_no_ui_text(de: SubscriptionLocale, fixture: str) -> None:
    offer = parse_product_page(read_fixture(f"de/{fixture}"), de).alternative_offer
    assert offer is None or offer.seller is None or not SELLER_UI_TEXT_RE.search(offer.seller)


@pytest.mark.parametrize("fixture", ["de/product-unavailable.html", "de/product-no-buybox.html"])
def test_product_without_price(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture, fixture: str) -> None:
    assert parse_product_page(read_fixture(fixture), de) == ProductPrices()
    assert "WARNING" not in caplog.text


def test_product_captcha(de: SubscriptionLocale) -> None:
    captcha = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'
    with pytest.raises(CaptchaError):
        parse_product_page(captcha, de)
