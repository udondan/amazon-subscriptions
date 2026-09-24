import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class IntervalUnit(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    #: The subscribed product is not available, e.g. a backup product is sent instead.
    UNAVAILABLE = "unavailable"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Interval:
    every: int
    unit: IntervalUnit


@dataclass
class Subscription:
    subscription_id: str
    asin: str | None = None
    title: str | None = None
    product_url: str | None = None
    image_url: str | None = None
    quantity: int | None = None
    interval: Interval | None = None
    next_delivery_date: datetime.date | None = None
    status: SubscriptionStatus = SubscriptionStatus.UNKNOWN
    #: Regular price of one unit. Not shown on the pages that are read, so far always ``None``.
    price: Decimal | None = None
    #: List price (RRP) of one unit. Not shown on the pages that are read, so far always ``None``.
    list_price: Decimal | None = None
    #: Subscribe & Save discount of the next delivery in percent.
    discount_percent: int | None = None
    #: Price of the next delivery of this subscription, for the whole quantity and with the discount applied.
    subscription_price: Decimal | None = None
    #: Price per unit of measure (e.g. per kg). Not shown on the pages that are read, so far always ``None``.
    unit_price: Decimal | None = None
    unit_price_unit: str | None = None
    #: ISO 4217 code of the amounts.
    currency: str | None = None
    #: Status text shown by Amazon, if any.
    raw_status_text: str | None = None


@dataclass
class DeliveryItem:
    title: str
    quantity: int | None = None
    interval: Interval | None = None
    #: Price for the whole quantity, with the discount applied.
    price: Decimal | None = None
    discount_percent: int | None = None
    #: Alert shown for the item, e.g. that a backup product is sent.
    alert_text: str | None = None
    #: ``True`` if a backup product is sent instead of the subscribed one.
    substitute: bool = False
    #: The subscription of this item. Delivery pages do not link items to subscriptions, so they are matched by
    #: title (see :func:`amazon_subscriptions.parse.matching.match_deliveries`). ``None`` if no unique match.
    subscription_id: str | None = None
    asin: str | None = None


@dataclass
class DiscountTier:
    #: Number of items (products) in the delivery.
    item_count: int | None = None
    #: ``True`` if Amazon states that the maximum discount is unlocked for this delivery.
    max_discount_unlocked: bool | None = None
    #: Total savings of the delivery as stated by Amazon.
    savings: Decimal | None = None


@dataclass
class UpcomingDelivery:
    date: datetime.date
    change_deadline: datetime.date | None = None
    items: list[DeliveryItem] = field(default_factory=list)
    discount_tier: DiscountTier = field(default_factory=DiscountTier)
    #: Sum of the item prices. ``None`` if any item has no price (yet).
    total: Decimal | None = None
    currency: str | None = None
    delivery_bundle_id: str | None = None
    #: Path of the delivery page, relative to the storefront.
    url: str | None = None
