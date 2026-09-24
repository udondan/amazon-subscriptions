import json
from datetime import date
from decimal import Decimal

from amazon_subscriptions.models import (
    DeliveryItem,
    Interval,
    IntervalUnit,
    Subscription,
    SubscriptionStatus,
    UpcomingDelivery,
)
from amazon_subscriptions.serialize import to_json, to_json_value


def test_subscription() -> None:
    subscription = Subscription(
        subscription_id="S1",
        interval=Interval(2, IntervalUnit.MONTH),
        next_delivery_date=date(2026, 10, 1),
        status=SubscriptionStatus.ACTIVE,
        subscription_price=Decimal("4.50"),
        currency="EUR",
    )
    value = to_json_value(subscription)
    assert value["interval"] == {"every": 2, "unit": "month"}
    assert value["next_delivery_date"] == "2026-10-01"
    assert value["status"] == "active"
    assert value["subscription_price"] == "4.50"
    assert value["price"] is None


def test_delivery() -> None:
    delivery = UpcomingDelivery(
        date=date(2026, 10, 1),
        items=[DeliveryItem(title="Testartikel 01", price=Decimal("1.99"))],
        total=Decimal("1.99"),
    )
    value = json.loads(to_json([delivery]))
    assert value[0]["date"] == "2026-10-01"
    assert value[0]["items"][0]["price"] == "1.99"
    assert value[0]["discount_tier"] == {"item_count": None, "max_discount_unlocked": None, "savings": None}


def test_keeps_umlauts() -> None:
    assert to_json(DeliveryItem(title="Müsli"), indent=None).startswith('{"title": "Müsli"')
