"""Link delivery items to subscriptions.

Delivery pages show neither ASIN nor subscription id, and the product images differ from the ones of the
subscription tiles. The only link is the title, which on delivery pages is often a shortened version of the
subscription's title. So an item is matched to a subscription by, in this order:

1. equal title,
2. the item's title being the first words of the subscription's title,
3. elimination: a backup product (see :attr:`DeliveryItem.substitute`) is matched to the only subscription due on
   the delivery date that has no item yet, if quantity and interval are the same.

Each step only matches if exactly one subscription qualifies. Items without a unique match keep
``subscription_id=None``. Titles are never matched by similarity, since a wrong match is worse than none.
"""

import logging
from collections.abc import Callable, Sequence

from amazon_subscriptions.models import DeliveryItem, Subscription, SubscriptionStatus, UpcomingDelivery

logger = logging.getLogger(__name__)


def _words(title: str | None) -> list[str]:
    return (title or "").rstrip(" .…").casefold().split()


def _is_prefix(item: DeliveryItem, subscription: Subscription) -> bool:
    item_words, subscription_words = _words(item.title), _words(subscription.title)
    return 0 < len(item_words) < len(subscription_words) and subscription_words[: len(item_words)] == item_words


def _is_equal(item: DeliveryItem, subscription: Subscription) -> bool:
    return bool(_words(item.title)) and _words(item.title) == _words(subscription.title)


def _link(item: DeliveryItem, subscription: Subscription) -> None:
    item.subscription_id = subscription.subscription_id
    item.asin = subscription.asin


def match_delivery(delivery: UpcomingDelivery, subscriptions: Sequence[Subscription]) -> None:
    """Link the items of a delivery to their subscriptions, see the module documentation."""
    unmatched = list(subscriptions)
    open_items = [item for item in delivery.items if item.subscription_id is None]

    rule: Callable[[DeliveryItem, Subscription], bool]
    for rule in (_is_equal, _is_prefix):
        for item in list(open_items):
            candidates = [s for s in unmatched if rule(item, s)]
            if len(candidates) == 1:
                _link(item, candidates[0])
                unmatched.remove(candidates[0])
                open_items.remove(item)
            elif len(candidates) > 1:
                logger.warning(f"Item {item.title!r} of {delivery.date} matches {len(candidates)} subscriptions.")

    substitutes = [item for item in open_items if item.substitute]
    due = [s for s in unmatched if s.next_delivery_date == delivery.date]
    if len(substitutes) == 1 and len(due) == 1:
        item, subscription = substitutes[0], due[0]
        if (item.quantity, item.interval) == (subscription.quantity, subscription.interval):
            _link(item, subscription)
            open_items.remove(item)

    for item in open_items:
        logger.warning(f"Item {item.title!r} of {delivery.date} matches no subscription.")


def apply_next_delivery(subscriptions: Sequence[Subscription], deliveries: Sequence[UpcomingDelivery]) -> None:
    """Copy price and discount of each subscription's next delivery to the subscription.

    A subscription whose next delivery sends a backup product gets the status ``unavailable`` and the item's alert as
    status text, but no price, since the price is the one of the backup product.
    """
    by_id = {s.subscription_id: s for s in subscriptions}
    for delivery in deliveries:
        for item in delivery.items:
            subscription = by_id.get(item.subscription_id or "")
            if subscription is None or subscription.next_delivery_date != delivery.date:
                continue
            if item.substitute:
                subscription.status = SubscriptionStatus.UNAVAILABLE
                subscription.raw_status_text = item.alert_text
                continue
            subscription.subscription_price = item.price
            subscription.discount_percent = item.discount_percent


def match_deliveries(subscriptions: Sequence[Subscription], deliveries: Sequence[UpcomingDelivery]) -> None:
    """Link the items of all deliveries to their subscriptions and copy the next delivery's data to them."""
    for delivery in deliveries:
        match_delivery(delivery, subscriptions)
    apply_next_delivery(subscriptions, deliveries)
