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


class ListPriceType(str, Enum):
    """What the list price of a product page is, by its label."""

    #: Recommended retail price, "UVP" on amazon.de.
    UVP = "uvp"
    #: Lowest price of the last 30 days.
    LOWEST_30D = "lowest_30d"
    #: A former price, "Statt" on amazon.de.
    WAS = "was"


class ListPriceSource(str, Enum):
    """The block of a product page the list price was read from."""

    #: The price block of the offer in the buybox.
    BUYBOX = "buybox"
    #: The entry of the product itself ("Dieser Artikel") in a comparison widget. Only recommended retail prices are
    #: read from there, as the widget may show another offer than the buybox.
    WIDGET = "widget"
    #: The price block of an alternative offer of the same product. Only recommended retail prices are read from there.
    ALTERNATIVE_OFFER = "alternative_offer"


@dataclass(frozen=True)
class Interval:
    every: int
    unit: IntervalUnit


@dataclass(frozen=True)
class AlternativeOffer:
    """An offer of the same product by another seller, listed next to the buybox offer."""

    #: Price of a one-time purchase.
    price: Decimal
    unit_price: Decimal | None = None
    unit_price_unit: str | None = None
    #: Name of the seller, if the page shows it.
    seller: str | None = None
    #: Alternative offers cannot be subscribed to.
    subscribable: bool = False


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
    #: Regular (one-time purchase) price of one unit. Only read with ``with_prices``, from the product page.
    price: Decimal | None = None
    #: List price of one unit, if the product page shows one for this product. Only read with ``with_prices``.
    list_price: Decimal | None = None
    #: What ``list_price`` is, by its label.
    list_price_type: ListPriceType | None = None
    #: The block of the product page ``list_price`` was read from.
    list_price_source: ListPriceSource | None = None
    #: Subscribe & Save discount of the next delivery in percent.
    discount_percent: int | None = None
    #: Price of the next delivery of this subscription, for the whole quantity and with the discount applied.
    subscription_price: Decimal | None = None
    #: Price per unit of measure of the regular price, e.g. per ``kg``. Only read with ``with_prices``.
    unit_price: Decimal | None = None
    #: The unit of measure of ``unit_price`` as shown by Amazon, e.g. ``kg``, ``100 ml`` or ``Stück``.
    unit_price_unit: str | None = None
    #: The cheapest other offer of the same product on the product page. Only read with ``with_prices``.
    alternative_offer: AlternativeOffer | None = None
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
    #: ASIN of the subscribed product, also if a backup product is sent instead.
    asin: str | None = None
    #: ASIN of the backup product if ``substitute`` is ``True``. ``title``, ``price`` and ``discount_percent`` are then
    #: the ones of the backup product. ``None`` if it could not be read from the subscription's detail sheet.
    substitute_asin: str | None = None


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
    #: URL of the delivery page.
    url: str | None = None
