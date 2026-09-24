from decimal import Decimal

import pytest

from amazon_subscriptions.exceptions import CaptchaError
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.parse import ProductPrices, parse_product_page
from tests.conftest import read_fixture


def test_product_with_list_price(de: SubscriptionLocale) -> None:
    prices = parse_product_page(read_fixture("de/product-list-price.html"), de)
    assert prices == ProductPrices(
        price=Decimal("17.49"), list_price=Decimal("27.99"), unit_price=Decimal("24.99"), unit_price_unit="l"
    )


def test_product(de: SubscriptionLocale) -> None:
    prices = parse_product_page(read_fixture("de/product.html"), de)
    assert prices == ProductPrices(price=Decimal("26.49"), unit_price=Decimal("0.25"), unit_price_unit="Stück")


def test_product_unavailable(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture) -> None:
    assert parse_product_page(read_fixture("de/product-unavailable.html"), de) == ProductPrices()
    assert "WARNING" not in caplog.text


def test_product_captcha(de: SubscriptionLocale) -> None:
    captcha = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'
    with pytest.raises(CaptchaError):
        parse_product_page(captcha, de)
