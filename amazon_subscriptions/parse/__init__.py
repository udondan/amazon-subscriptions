"""Pure functions that turn Subscribe & Save pages into objects. They send no requests."""

from amazon_subscriptions.parse.acp import AcpWidget, parse_acp_widget
from amazon_subscriptions.parse.deliveries import (
    parse_deliveries_next_url,
    parse_delivery_cards,
    parse_delivery_page,
)
from amazon_subscriptions.parse.detail import BackupItem, parse_subscription_detail
from amazon_subscriptions.parse.matching import match_deliveries, titles_match
from amazon_subscriptions.parse.subscriptions import parse_subscriptions, parse_subscriptions_next_url

__all__ = [
    "AcpWidget",
    "BackupItem",
    "match_deliveries",
    "parse_acp_widget",
    "parse_deliveries_next_url",
    "parse_delivery_cards",
    "parse_delivery_page",
    "parse_subscription_detail",
    "parse_subscriptions",
    "parse_subscriptions_next_url",
    "titles_match",
]
