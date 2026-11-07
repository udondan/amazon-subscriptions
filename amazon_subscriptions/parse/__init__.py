"""Pure functions that turn Subscribe & Save pages into objects. They send no requests."""

from amazon_subscriptions.parse.acp import AcpWidget, parse_acp_widget
from amazon_subscriptions.parse.deliveries import (
    merge_delivery_card,
    parse_deliveries_next_url,
    parse_delivery_cards,
    parse_delivery_page,
)
from amazon_subscriptions.parse.detail import BackupItem, parse_subscription_detail
from amazon_subscriptions.parse.matching import (
    apply_delivery_errors,
    match_deliveries,
    set_substitute_asin,
    titles_match,
)
from amazon_subscriptions.parse.product import ProductPrices, parse_product_page
from amazon_subscriptions.parse.subscriptions import parse_subscriptions, parse_subscriptions_next_url

__all__ = [
    "AcpWidget",
    "BackupItem",
    "ProductPrices",
    "apply_delivery_errors",
    "match_deliveries",
    "merge_delivery_card",
    "parse_acp_widget",
    "parse_deliveries_next_url",
    "parse_delivery_cards",
    "parse_delivery_page",
    "parse_product_page",
    "parse_subscription_detail",
    "parse_subscriptions",
    "parse_subscriptions_next_url",
    "set_substitute_asin",
    "titles_match",
]
