from datetime import date
from decimal import Decimal

import pytest

from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import DeliveryItem, Interval, IntervalUnit, Subscription, UpcomingDelivery
from amazon_subscriptions.parse import match_deliveries, parse_delivery_page, parse_subscriptions
from amazon_subscriptions.parse.matching import match_delivery, titles_match
from tests.conftest import DE_TODAY, delivery_1_with_backup_product, read_fixture, substitute_item_title

MONTHLY = Interval(1, IntervalUnit.MONTH)


@pytest.fixture
def matched(de: SubscriptionLocale) -> tuple[list[Subscription], list[UpcomingDelivery]]:
    subscriptions = parse_subscriptions(read_fixture("de/landing.html"), de, DE_TODAY)
    deliveries = [parse_delivery_page(read_fixture(f"de/delivery-{i}.html"), de) for i in (1, 2)]
    match_deliveries(subscriptions, deliveries)
    return subscriptions, deliveries


def _by_id(subscriptions: list[Subscription]) -> dict[str, Subscription]:
    return {s.subscription_id: s for s in subscriptions}


def _by_title(subscriptions: list[Subscription], prefix: str) -> Subscription:
    [subscription] = [s for s in subscriptions if s.title and s.title.startswith(prefix)]
    return subscription


def test_all_items_matched(
    matched: tuple[list[Subscription], list[UpcomingDelivery]], caplog: pytest.LogCaptureFixture
) -> None:
    subscriptions, deliveries = matched
    by_id = _by_id(subscriptions)
    for delivery in deliveries:
        ids = [item.subscription_id for item in delivery.items]
        assert None not in ids
        assert len(set(ids)) == len(ids)
        for item in delivery.items:
            subscription = by_id[item.subscription_id or ""]
            assert item.asin == subscription.asin
            assert (item.quantity, item.interval) == (subscription.quantity, subscription.interval)
            assert subscription.title and subscription.title.startswith(item.title.rstrip(" .…"))
    assert "matches" not in caplog.text


def test_substitute(de: SubscriptionLocale) -> None:
    # The first item of the first delivery as a backup product
    subscriptions = parse_subscriptions(read_fixture("de/landing.html"), de, DE_TODAY)
    page = delivery_1_with_backup_product().replace(substitute_item_title(), "Product 50 backup product")
    delivery = parse_delivery_page(page, de)
    match_deliveries(subscriptions, [delivery])

    [substitute] = [item for item in delivery.items if item.substitute]
    subscription = _by_id(subscriptions)[substitute.subscription_id or ""]
    assert substitute.title == "Product 50 backup product"
    assert subscription.title and subscription.title.startswith("Product 01 ")
    assert subscription.subscription_price is None
    assert subscription.discount_percent is None


def test_next_delivery_prices(matched: tuple[list[Subscription], list[UpcomingDelivery]]) -> None:
    subscriptions, _ = matched
    second = _by_title(subscriptions, "Product 02 ")
    assert (second.subscription_price, second.discount_percent) == (Decimal("12.74"), 15)
    priced = [s for s in subscriptions if s.subscription_price is not None]
    assert len(priced) == 5
    assert all(s.next_delivery_date == date(2026, 11, 1) for s in priced)
    # Deliveries after the next one of a subscription, here without prices, do not overwrite its price
    assert _by_title(subscriptions, "Product 05 ").subscription_price == Decimal("18.95")
    # The first delivery of a subscription sets the discount even if it has no prices yet
    later = _by_title(subscriptions, "Product 13 ")
    assert later.next_delivery_date == date(2026, 12, 1)
    assert later.subscription_price is None
    assert later.discount_percent == 15


def _subscription(subscription_id: str, title: str, next_delivery: date | None = None) -> Subscription:
    return Subscription(subscription_id, title=title, quantity=1, interval=MONTHLY, next_delivery_date=next_delivery)


def _delivery(*items: DeliveryItem) -> UpcomingDelivery:
    return UpcomingDelivery(date=date(2026, 10, 1), items=list(items))


def test_ambiguous_prefix_is_not_matched(caplog: pytest.LogCaptureFixture) -> None:
    subscriptions = [_subscription("A", "Product lorem ipsum"), _subscription("B", "Product lorem dolor")]
    delivery = _delivery(DeliveryItem("Product lorem…", 1, MONTHLY))
    match_delivery(delivery, subscriptions)
    assert delivery.items[0].subscription_id is None
    assert "matches 2 subscriptions" in caplog.text


def test_exact_match_wins_over_prefix() -> None:
    subscriptions = [_subscription("A", "Product lorem"), _subscription("B", "Product lorem ipsum")]
    delivery = _delivery(DeliveryItem("Product lorem", 1, MONTHLY), DeliveryItem("Product lorem …", 1, MONTHLY))
    match_delivery(delivery, subscriptions)
    assert [item.subscription_id for item in delivery.items] == ["A", "B"]


def test_substitute_needs_same_quantity_and_interval() -> None:
    subscriptions = [_subscription("A", "Product lorem", date(2026, 10, 1))]
    item = DeliveryItem("Product ipsum", 2, MONTHLY, substitute=True)
    match_delivery(_delivery(item), subscriptions)
    assert item.subscription_id is None


def test_substitute_needs_unique_candidate() -> None:
    subscriptions = [
        _subscription("A", "Product lorem", date(2026, 10, 1)),
        _subscription("B", "Product dolor", date(2026, 10, 1)),
    ]
    item = DeliveryItem("Product ipsum", 1, MONTHLY, substitute=True)
    match_delivery(_delivery(item), subscriptions)
    assert item.subscription_id is None


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("Product lorem", "Product lorem", True),
        ("Product lorem …", "Product lorem ipsum", True),
        ("Product lorem ipsum", "product lorem", True),
        ("Product lorem", "Product ipsum", False),
        ("", "Product", False),
        (None, None, False),
    ],
)
def test_titles_match(a: str | None, b: str | None, expected: bool) -> None:
    assert titles_match(a, b) is expected
