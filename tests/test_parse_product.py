import re
from decimal import Decimal

import pytest

from amazon_subscriptions.exceptions import CaptchaError
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import AlternativeOffer, ListPriceSource, ListPriceType
from amazon_subscriptions.parse import ProductPrices, parse_product_page
from amazon_subscriptions.serialize import to_json
from tests.conftest import FIXTURES, read_fixture

#: The label of the list price in the price display of an offer
DISPLAY_LABEL = 'apex-basisprice-label">UVP:<'
#: The label of the list price in the entry "Dieser Artikel" of the comparison widget
WIDGET_LABEL = "<span>UVP:</span>"
#: Texts of the page around the seller name, which are never one
SELLER_UI_TEXT_RE = re.compile(r"weitere informationen|details|verkäufer|versender|mehr anzeigen", re.IGNORECASE)
#: The collapsed seller name of the alternative offer on a page loaded with a session
SIGNED_IN_SELLER = 'tertiary offer-display-feature-text-message">Testhändler 02<'


def test_product_with_list_price(de: SubscriptionLocale) -> None:
    prices = parse_product_page(read_fixture("de/product-list-price.html"), de)
    assert prices == ProductPrices(
        price=Decimal("17.49"),
        list_price=Decimal("27.99"),
        list_price_type=ListPriceType.UVP,
        list_price_source=ListPriceSource.BUYBOX,
        unit_price=Decimal("24.99"),
        unit_price_unit="l",
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    [("Niedrigster Preis in 30 Tagen:", ListPriceType.LOWEST_30D), ("Statt:", ListPriceType.WAS)],
)
def test_product_list_price_type(de: SubscriptionLocale, label: str, expected: ListPriceType) -> None:
    html = read_fixture("de/product-list-price.html").replace(DISPLAY_LABEL, f'apex-basisprice-label">{label}<')
    prices = parse_product_page(html, de)
    assert (prices.list_price, prices.list_price_type, prices.list_price_source) == (
        Decimal("27.99"),
        expected,
        ListPriceSource.BUYBOX,
    )


def test_product_list_price_unknown_label(de: SubscriptionLocale) -> None:
    html = read_fixture("de/product-list-price.html").replace(DISPLAY_LABEL, 'apex-basisprice-label">Früher:<')
    prices = parse_product_page(html, de)
    assert (prices.price, prices.list_price, prices.list_price_type) == (Decimal("17.49"), None, None)


def test_product_price_display_of_another_price(de: SubscriptionLocale) -> None:
    # A price display that does not show the price of its offer belongs to something else
    html = read_fixture("de/product-list-price.html").replace('a-price-whole">17<', 'a-price-whole">18<', 1)
    prices = parse_product_page(html, de)
    assert (prices.price, prices.list_price) == (Decimal("17.49"), None)


def test_product(de: SubscriptionLocale) -> None:
    prices = parse_product_page(read_fixture("de/product.html"), de)
    assert prices == ProductPrices(price=Decimal("26.49"), unit_price=Decimal("0.25"), unit_price_unit="Stück")


def test_product_alternative_offer(de: SubscriptionLocale) -> None:
    prices = parse_product_page(read_fixture("de/product-alternative-offer.html"), de)
    assert prices == ProductPrices(
        price=Decimal("5.98"),
        list_price=Decimal("5.75"),
        list_price_type=ListPriceType.UVP,
        list_price_source=ListPriceSource.WIDGET,
        unit_price=Decimal("1.50"),
        unit_price_unit="Stück",
        alternative_offer=AlternativeOffer(
            price=Decimal("5.45"),
            unit_price=Decimal("1.36"),
            unit_price_unit="Stück",
            seller="Testhändler 02",
            subscribable=False,
        ),
    )


def test_product_alternative_offer_signed_in(de: SubscriptionLocale) -> None:
    # Signed in, #sellerProfileTriggerId is the link "Weitere Informationen über den Verkäufer" of the seller popover
    prices = parse_product_page(read_fixture("de/product-alternative-offer-signed-in.html"), de)
    assert prices == ProductPrices(
        price=Decimal("5.98"),
        list_price=Decimal("5.75"),
        list_price_type=ListPriceType.UVP,
        list_price_source=ListPriceSource.WIDGET,
        unit_price=Decimal("1.50"),
        unit_price_unit="Stück",
        alternative_offer=AlternativeOffer(
            price=Decimal("5.45"),
            unit_price=Decimal("1.36"),
            unit_price_unit="Stück",
            seller="Testhändler 02",
            seller_id="A0TESTSELLER02",
            subscribable=False,
        ),
    )


def test_product_alternative_offer_sold_by_amazon(de: SubscriptionLocale) -> None:
    # Amazon has no seller profile link
    html = (
        read_fixture("de/product-alternative-offer-signed-in.html")
        .replace(SIGNED_IN_SELLER, 'tertiary offer-display-feature-text-message">Amazon<')
        .replace('?seller=A0TESTSELLER02" id="sellerProfileTriggerId"', '"')
    )
    offer = parse_product_page(html, de).alternative_offer
    assert offer is not None
    assert (offer.seller, offer.seller_id) == ("Amazon", None)


def test_product_alternative_offer_without_seller(de: SubscriptionLocale) -> None:
    html = read_fixture("de/product-alternative-offer-signed-in.html").replace(
        SIGNED_IN_SELLER, 'tertiary offer-display-feature-text-message"> <'
    )
    offer = parse_product_page(html, de).alternative_offer
    assert offer is not None
    assert (offer.seller, offer.seller_id) == (None, "A0TESTSELLER02")


@pytest.mark.parametrize("fixture", sorted(path.name for path in (FIXTURES / "de").glob("product*.html")))
def test_product_seller_is_no_ui_text(de: SubscriptionLocale, fixture: str) -> None:
    offer = parse_product_page(read_fixture(f"de/{fixture}"), de).alternative_offer
    assert offer is None or offer.seller is None or not SELLER_UI_TEXT_RE.search(offer.seller)


def test_product_alternative_offer_no_foreign_prices(de: SubscriptionLocale) -> None:
    html = read_fixture("de/product-alternative-offer.html")
    # The page shows them for a sponsored product, another variant and the products of the comparison widget
    foreign = ["9.59", "11.90", "10.17", "7.53", "0.94"]
    assert all(price.replace(".", ",") in html for price in foreign)
    serialized = to_json(parse_product_page(html, de))
    assert [price for price in foreign if price in serialized] == []


def test_product_list_price_of_the_alternative_offer(de: SubscriptionLocale) -> None:
    # Without the widget, the recommended retail price shown for the alternative offer is used
    html = read_fixture("de/product-alternative-offer.html").replace(WIDGET_LABEL, "<span>Statt:</span>")
    prices = parse_product_page(html, de)
    assert (prices.list_price, prices.list_price_type, prices.list_price_source) == (
        Decimal("5.75"),
        ListPriceType.UVP,
        ListPriceSource.ALTERNATIVE_OFFER,
    )


def test_product_other_list_prices_of_the_alternative_offer(de: SubscriptionLocale) -> None:
    # Other list prices of the widget entry and of the alternative offer only apply to the alternative offer
    html = (
        read_fixture("de/product-alternative-offer.html")
        .replace(WIDGET_LABEL, "<span>Statt:</span>")
        .replace(DISPLAY_LABEL, 'apex-basisprice-label">Statt:<')
    )
    prices = parse_product_page(html, de)
    assert (prices.price, prices.list_price, prices.list_price_type, prices.list_price_source) == (
        Decimal("5.98"),
        None,
        None,
        None,
    )


def test_product_widget_entry_of_another_product(de: SubscriptionLocale) -> None:
    html = read_fixture("de/product-alternative-offer.html").replace(
        "/product-reviews/B0TESTP003/", "/product-reviews/B0TESTX009/"
    )
    assert parse_product_page(html, de).list_price_source is ListPriceSource.ALTERNATIVE_OFFER


def test_product_unavailable(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture) -> None:
    assert parse_product_page(read_fixture("de/product-unavailable.html"), de) == ProductPrices()
    assert "WARNING" not in caplog.text


def test_product_captcha(de: SubscriptionLocale) -> None:
    captcha = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'
    with pytest.raises(CaptchaError):
        parse_product_page(captcha, de)
