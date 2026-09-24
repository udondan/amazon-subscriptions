from datetime import date
from decimal import Decimal

import pytest

from amazon_subscriptions.exceptions import PageStructureError
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import Interval, IntervalUnit, ParseError, UpcomingDelivery
from amazon_subscriptions.parse import parse_deliveries_next_url, parse_delivery_cards, parse_delivery_page
from tests.conftest import DE_DELIVERY_1_EPOCH, DE_LANDING_URL, delivery_1_without_date, read_fixture


@pytest.fixture(scope="module")
def delivery_1(de: SubscriptionLocale) -> UpcomingDelivery:
    return parse_delivery_page(read_fixture("de/delivery-1.html"), de)


@pytest.fixture(scope="module")
def delivery_2(de: SubscriptionLocale) -> UpcomingDelivery:
    return parse_delivery_page(read_fixture("de/delivery-2.html"), de)


def test_delivery_cards(de: SubscriptionLocale) -> None:
    cards = parse_delivery_cards(read_fixture("de/landing.html"), de)
    assert [(c.date, c.change_deadline, c.discount_tier.item_count) for c in cards] == [
        (date(2026, 10, 1), date(2026, 9, 26), 11),
        (date(2026, 11, 1), date(2026, 10, 27), 16),
    ]
    for card in cards:
        assert card.items == []
        assert card.delivery_bundle_id
        assert card.url and "deliveryDate=" in card.url
        assert card.currency == "EUR"


def test_deliveries_next_url() -> None:
    next_url = parse_deliveries_next_url(read_fixture("de/landing.html"))
    assert next_url and "/replenishment/fulfillment/deliveries" in next_url
    assert parse_deliveries_next_url(read_fixture("de/subscriptions-page-2.html")) is None


def test_delivery_cards_missing(de: SubscriptionLocale) -> None:
    with pytest.raises(PageStructureError, match="No deliveries found"):
        parse_delivery_cards(read_fixture("de/subscriptions-page-2.html"), de)


def test_delivery_1(delivery_1: UpcomingDelivery) -> None:
    assert delivery_1.date == date(2026, 10, 1)
    assert delivery_1.change_deadline == date(2026, 9, 26)
    assert len(delivery_1.items) == 11
    assert delivery_1.discount_tier.item_count == 11
    assert delivery_1.discount_tier.max_discount_unlocked is True
    assert delivery_1.discount_tier.savings == Decimal("25.32")
    assert delivery_1.currency == "EUR"
    assert all(item.price is not None for item in delivery_1.items)
    assert delivery_1.total == sum((item.price or Decimal(0) for item in delivery_1.items), Decimal(0))
    assert delivery_1.total == Decimal("150.19")


def test_delivery_1_items(delivery_1: UpcomingDelivery) -> None:
    first, second = delivery_1.items[:2]
    assert first.title.startswith("Testartikel 50 ")
    assert first.quantity == 1
    assert first.interval == Interval(1, IntervalUnit.MONTH)
    assert first.price == Decimal("9.49")
    assert first.discount_percent == 5
    assert first.substitute is True
    assert first.alert_text == "Backup-Produkt wird versendet"

    assert second.title.startswith("Testartikel 02 ")
    assert second.interval == Interval(5, IntervalUnit.MONTH)
    assert second.price == Decimal("6.76")
    assert second.discount_percent == 15
    assert second.substitute is False
    assert second.alert_text is None

    assert [item.substitute for item in delivery_1.items].count(True) == 1
    assert all(item.subscription_id is None for item in delivery_1.items)


def test_delivery_2_without_prices(delivery_2: UpcomingDelivery) -> None:
    assert delivery_2.date == date(2026, 11, 1)
    assert delivery_2.change_deadline == date(2026, 10, 27)
    assert len(delivery_2.items) == 16
    assert delivery_2.discount_tier.item_count == 16
    assert delivery_2.discount_tier.max_discount_unlocked is True
    assert delivery_2.discount_tier.savings is None
    assert all(item.price is None for item in delivery_2.items)
    assert delivery_2.total is None
    assert all(item.discount_percent in (5, 15) for item in delivery_2.items)
    assert all(item.quantity and item.interval for item in delivery_2.items)
    assert not any(item.substitute for item in delivery_2.items)


def test_delivery_page_without_date_takes_it_from_the_url(de: SubscriptionLocale) -> None:
    url = f"{DE_LANDING_URL}/?shipId=x&deliveryDate={DE_DELIVERY_1_EPOCH}&deliveryBundleId=y"
    delivery = parse_delivery_page(delivery_1_without_date(), de, url)

    # Midnight in Europe/Berlin, which is still 30 September in UTC
    assert delivery.date == date(2026, 10, 1)
    assert len(delivery.items) == 11
    assert delivery.total == Decimal("150.19")
    assert delivery.parse_errors == [
        ParseError(
            url=url,
            message="No delivery date found, it was taken from the URL",
            selector="[data-testid='ddp-atd-delivery-date']",
        )
    ]


def test_delivery_page_without_date_and_url(de: SubscriptionLocale) -> None:
    with pytest.raises(PageStructureError, match="No delivery date found") as e:
        parse_delivery_page(delivery_1_without_date(), de, f"{DE_LANDING_URL}/?shipId=x")
    assert e.value.selector == "[data-testid='ddp-atd-delivery-date']"


def test_delivery_page_with_date_has_no_errors(delivery_1: UpcomingDelivery) -> None:
    assert delivery_1.parse_errors == []


def test_delivery_page_unknown(de: SubscriptionLocale) -> None:
    with pytest.raises(PageStructureError, match="No delivery date found"):
        parse_delivery_page(read_fixture("de/landing.html"), de)
