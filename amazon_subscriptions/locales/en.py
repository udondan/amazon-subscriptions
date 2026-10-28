import re
from typing import ClassVar

from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import IntervalUnit, ListPriceType, SubscriptionStatus

_MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]  # fmt: skip


class EnglishSubscriptionLocale(SubscriptionLocale):
    """The Subscribe & Save pages in English, as every storefront that offers English shows them.

    Dates are read in both orders, "1 Oct" and "Oct 1", and amounts as "1,234.56".
    """

    MONTHS: ClassVar[dict[str, int]] = {
        **{name: number for number, name in enumerate(_MONTH_NAMES, 1)},
        **{name[:3]: number for number, name in enumerate(_MONTH_NAMES, 1)},
        "sept": 9,
    }
    DATE_PATTERNS: ClassVar[list[str]] = [
        # 1 Oct, 1st October 2026, Thu, 1 Oct
        r"(?<![\d.,])(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>{months})\.?(?![a-z])(?:,?\s+(?P<year>\d{4}))?(?!\d)",
        # Oct 1, October 1st, 2026, Thu, Oct 1
        r"(?<![a-z])(?P<month>{months})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?![\d.,]\d)(?:,?\s+(?P<year>\d{4}))?(?!\d)",
    ]

    NEXT_DELIVERY_PREFIX = "Next delivery:"
    TILE_ACTION_TEXTS: ClassVar[list[str]] = ["Edit or cancel"]
    # TODO: capture tiles of paused and unavailable subscriptions to fill this
    STATUS_TEXTS: ClassVar[dict[str, SubscriptionStatus]] = {}
    ARRIVAL_PREFIX = "Arriving"
    DEADLINE_PREFIX = "Last day to edit"

    QUANTITY_INTERVAL_RE = re.compile(
        r"(\d+) units? every (?:(\d+) )?(day|days|week|weeks|month|months)", re.IGNORECASE
    )
    INTERVAL_UNITS: ClassVar[dict[str, IntervalUnit]] = {
        "day": IntervalUnit.DAY, "days": IntervalUnit.DAY,
        "week": IntervalUnit.WEEK, "weeks": IntervalUnit.WEEK,
        "month": IntervalUnit.MONTH, "months": IntervalUnit.MONTH,
    }  # fmt: skip
    DISCOUNT_PERCENT_RE = re.compile(r"Saving (\d{1,2}) ?%", re.IGNORECASE)
    ITEM_COUNT_RE = re.compile(r"(\d+) items?\b")
    # TODO: capture a delivery whose savings show an amount to fill this
    SAVINGS_RE = None
    MAX_DISCOUNT_UNLOCKED_TEXT = "Max savings unlocked"
    SUBSTITUTE_ALERT_TEXTS: ClassVar[list[str]] = ["Backup product will be shipped"]

    UNIT_PRICE_RE = re.compile(r"(.+?) per (.+)")
    # TODO: capture the label of the lowest price of the last 30 days to add it
    LIST_PRICE_TYPES: ClassVar[dict[str, ListPriceType]] = {
        "RRP": ListPriceType.RRP,
        "Was": ListPriceType.WAS,
    }
    # TODO: capture a buybox with offers of other sellers to fill this. "Get it faster" is a faster delivery of the
    # same seller, not an alternative offer.
    ALTERNATIVE_OFFERS_CAPTIONS: ClassVar[list[str]] = []
    THIS_ITEM_LABEL = "This item:"

    AMOUNT_RE = re.compile(r"(-?(?:\d{1,3}(?:,\d{3})+|\d+))(?:\.(\d{1,2}))?")
    THOUSANDS_SEPARATOR = ","
