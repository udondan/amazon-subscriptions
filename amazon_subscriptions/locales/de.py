import re
from typing import ClassVar

from amazonorders.localization import DeDE

from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import IntervalUnit, SubscriptionStatus


class DeSubscriptionLocale(SubscriptionLocale):
    """The Subscribe & Save pages of amazon.de."""

    AMAZON_LOCALE = DeDE
    CURRENCY = "EUR"
    # The month names of amazon-orders' DeDE are private, so they are repeated here
    MONTHS: ClassVar[dict[str, int]] = {
        "januar": 1, "jan": 1, "jänner": 1,
        "februar": 2, "feb": 2,
        "märz": 3, "mär": 3, "mrz": 3,
        "april": 4, "apr": 4,
        "mai": 5,
        "juni": 6, "jun": 6,
        "juli": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sept": 9, "sep": 9,
        "oktober": 10, "okt": 10,
        "november": 11, "nov": 11,
        "dezember": 12, "dez": 12,
    }  # fmt: skip

    NEXT_DELIVERY_PREFIX = "Nächste Lieferung:"
    TILE_ACTION_TEXTS: ClassVar[list[str]] = ["Abo verwalten"]
    # TODO: capture tiles of paused and unavailable subscriptions to fill this
    STATUS_TEXTS: ClassVar[dict[str, SubscriptionStatus]] = {}
    ARRIVAL_PREFIX = "Ankunft:"
    DEADLINE_PREFIX = "Letzter Tag zum Bearbeiten"

    QUANTITY_INTERVAL_RE = re.compile(
        r"(\d+) Einheit(?:en)? (?:jeden|jede|jedes|alle|pro) (?:(\d+) )?"
        r"(Tag|Tage|Tagen|Woche|Wochen|Monat|Monate|Monaten)",
        re.IGNORECASE,
    )
    INTERVAL_UNITS: ClassVar[dict[str, IntervalUnit]] = {
        "tag": IntervalUnit.DAY, "tage": IntervalUnit.DAY, "tagen": IntervalUnit.DAY,
        "woche": IntervalUnit.WEEK, "wochen": IntervalUnit.WEEK,
        "monat": IntervalUnit.MONTH, "monate": IntervalUnit.MONTH, "monaten": IntervalUnit.MONTH,
    }  # fmt: skip
    DISCOUNT_PERCENT_RE = re.compile(r"Spare (\d{1,2}) ?%", re.IGNORECASE)
    ITEM_COUNT_RE = re.compile(r"(\d+) Artikel\b")
    SAVINGS_RE = re.compile(r"Ersparnis (-?[\d.]+(?:,\d{1,2})? ?€)")
    MAX_DISCOUNT_UNLOCKED_TEXT = "Maximale Einsparungen freigeschaltet"
    SUBSTITUTE_ALERT_TEXTS: ClassVar[list[str]] = ["Backup-Produkt wird versendet"]

    AMOUNT_RE = re.compile(r"(-?(?:\d{1,3}(?:\.\d{3})+|\d+))(?:,(\d{1,2}))?")
    THOUSANDS_SEPARATOR = "."
    AMOUNT_NOISE_RE = re.compile(r"€|EUR")
