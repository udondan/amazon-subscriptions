from datetime import date
from decimal import Decimal

from amazon_subscriptions.models import AlternativeOffer, DeliveryItem, Subscription, UpcomingDelivery
from amazon_subscriptions.text import format_delivery, format_subscription


def test_subscription_without_interval() -> None:
    subscription = Subscription(subscription_id="S1", asin="B0TEST0001", quantity=1)
    assert format_subscription(subscription) == "?  1 x B0TEST0001  (?)"


def test_subscription_with_alternative_offer() -> None:
    subscription = Subscription(
        subscription_id="S1",
        title="Product 01",
        price=Decimal("4.99"),
        alternative_offer=AlternativeOffer(price=Decimal("3.99"), seller="Seller 01"),
        currency="EUR",
    )
    assert format_subscription(subscription).endswith("(regular 4.99 EUR, alternative offer 3.99 EUR from Seller 01)")
    subscription.alternative_offer = AlternativeOffer(price=Decimal("3.99"))
    assert format_subscription(subscription).endswith("(regular 4.99 EUR, alternative offer 3.99 EUR)")


def test_delivery_with_backup_products() -> None:
    delivery = UpcomingDelivery(
        date=date(2026, 11, 1),
        items=[
            DeliveryItem(title="Product 01", quantity=1, substitute=True, substitute_asin="B0TEST0002"),
            DeliveryItem(title="Product 03", quantity=1, substitute=True),
        ],
        currency="EUR",
    )
    assert format_delivery(delivery).splitlines()[1:] == [
        "  1 x Product 01  -  [backup product B0TEST0002]",
        "  1 x Product 03  -  [backup product]",
    ]
