import re
from typing import ClassVar

from amazonorders.localization import DeDE

from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import IntervalUnit, ListPriceType, SubscriptionStatus


class DeSubscriptionLocale(SubscriptionLocale):
    """The Subscribe & Save pages of amazon.de."""

    AMAZON_LOCALE = DeDE
    CURRENCY = "EUR"
    TIMEZONE = "Europe/Berlin"

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

    UNIT_PRICE_RE = re.compile(r"(.+?) pro (.+)")
    LIST_PRICE_TYPES: ClassVar[dict[str, ListPriceType]] = {
        "UVP": ListPriceType.UVP,
        "Niedrigster Preis in 30 Tagen": ListPriceType.LOWEST_30D,
        "Statt": ListPriceType.WAS,
    }
    ALTERNATIVE_OFFERS_CAPTIONS: ClassVar[list[str]] = ["Alternative Angebote"]
    THIS_ITEM_LABEL = "Dieser Artikel"

    AMOUNT_RE = re.compile(r"(-?(?:\d{1,3}(?:\.\d{3})+|\d+))(?:,(\d{1,2}))?")
    THOUSANDS_SEPARATOR = "."
    AMOUNT_NOISE_RE = re.compile(r"€|EUR")
