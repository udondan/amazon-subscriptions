import html
import logging
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import ClassVar

from amazonorders.localization import Locale

from amazon_subscriptions.dates import DateParts
from amazon_subscriptions.exceptions import SubscriptionsError
from amazon_subscriptions.models import Interval, IntervalUnit, ListPriceType, SubscriptionStatus

logger = logging.getLogger(__name__)


def normalize_space(text: str) -> str:
    """Collapse all whitespace, including non-breaking spaces, into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


class SubscriptionLocale:
    """Texts and formats of the Subscribe & Save pages of one storefront.

    A storefront is supported by a subclass that sets the class attributes and is registered in
    :data:`amazon_subscriptions.locales.LOCALES_BY_TLD`.
    """

    #: The Locale of amazon-orders for the storefront, used for full dates and month names.
    AMAZON_LOCALE: ClassVar[type[Locale]]
    #: ISO 4217 code of the storefront's currency.
    CURRENCY: ClassVar[str]
    #: IANA time zone of the storefront, in which the timestamps of delivery links are midnight.
    TIMEZONE: ClassVar[str]

    #: Text before the next delivery date of a subscription tile.
    NEXT_DELIVERY_PREFIX: ClassVar[str]
    #: Texts of a subscription tile that are neither title, date, quantity nor a status (e.g. links).
    TILE_ACTION_TEXTS: ClassVar[list[str]]
    #: Status texts of a subscription tile, matched as prefix. Texts not listed give ``unknown`` and a warning.
    STATUS_TEXTS: ClassVar[dict[str, SubscriptionStatus]]
    #: Text shown instead of the subscriptions when there are none. ``None`` if not known yet.
    NO_SUBSCRIPTIONS_TEXT: ClassVar[str | None] = None

    #: Text before the arrival date of a delivery card.
    ARRIVAL_PREFIX: ClassVar[str]
    #: Text before the change deadline of a delivery card.
    DEADLINE_PREFIX: ClassVar[str]

    #: Quantity and interval, e.g. "3 Einheiten alle 2 Monate". Groups: quantity, every (optional), unit.
    QUANTITY_INTERVAL_RE: ClassVar[re.Pattern[str]]
    #: Unit words of intervals, lower case.
    INTERVAL_UNITS: ClassVar[dict[str, IntervalUnit]]
    #: Discount of an item, e.g. "Spare 15 %". Group: percent.
    DISCOUNT_PERCENT_RE: ClassVar[re.Pattern[str]]
    #: Number of items of a delivery, e.g. "11 Artikel". Group: count.
    ITEM_COUNT_RE: ClassVar[re.Pattern[str]]
    #: Total savings of a delivery, e.g. "Ersparnis 25,32 €". Group: amount.
    SAVINGS_RE: ClassVar[re.Pattern[str]]
    #: Text stating that the maximum discount of a delivery is unlocked.
    MAX_DISCOUNT_UNLOCKED_TEXT: ClassVar[str]
    #: Item alerts stating that a backup product is sent instead of the subscribed one.
    SUBSTITUTE_ALERT_TEXTS: ClassVar[list[str]]

    #: Unit price of a product page, e.g. "24,99 € pro l". Groups: amount, unit.
    UNIT_PRICE_RE: ClassVar[re.Pattern[str]]
    #: Labels of the list price of a product page by the type they state, matched as prefix.
    LIST_PRICE_TYPES: ClassVar[dict[str, ListPriceType]]
    #: Captions of the buybox rows with offers of other sellers.
    ALTERNATIVE_OFFERS_CAPTIONS: ClassVar[list[str]]
    #: Label of the entry of the product itself in a comparison widget, e.g. "Dieser Artikel:", matched as prefix.
    THIS_ITEM_LABEL: ClassVar[str]

    #: Amount pattern, e.g. "1.234,56". Groups: integer part, decimals (optional).
    AMOUNT_RE: ClassVar[re.Pattern[str]]
    #: Thousands separator of :attr:`AMOUNT_RE`.
    THOUSANDS_SEPARATOR: ClassVar[str]
    #: Texts around an amount that are not part of it, e.g. currency symbols.
    AMOUNT_NOISE_RE: ClassVar[re.Pattern[str]]

    def __init__(self) -> None:
        self.amazon_locale = self.AMAZON_LOCALE()
        self.months: Mapping[str, int] = self.amazon_locale.MONTHS
        if not self.months:
            raise SubscriptionsError(f"{self.AMAZON_LOCALE.__name__} of amazon-orders defines no month names.")
        months = "|".join(sorted(map(re.escape, self.months), key=len, reverse=True))
        self._date_re = re.compile(
            r"(?<!\d)(\d{1,2})\.\s*(" + months + r")\.?(?![a-zäöü])(?:\s+(\d{4}))?(?!\d)", re.IGNORECASE
        )

    def parse_amount(self, text: str | None) -> Decimal | None:
        """Parse an amount such as ``1.234,56 €``. The text must contain nothing else."""
        if not text:
            return None
        value = normalize_space(self.AMOUNT_NOISE_RE.sub("", normalize_space(text))).replace(" ", "")
        match = self.AMOUNT_RE.fullmatch(value)
        if not match:
            logger.warning(f"Amount {text!r} was not recognized, so it was not parsed.")
            return None
        integer, decimals = match.group(1), match.group(2) or "0"
        try:
            return Decimal(f"{integer.replace(self.THOUSANDS_SEPARATOR, '')}.{decimals}")
        except InvalidOperation:  # pragma: no cover, the pattern only matches digits
            return None

    def parse_date_parts(self, text: str | None) -> DateParts | None:
        """Parse the single date in a text such as ``Ankunft: Do., 1. Okt.``, with or without year."""
        if not text:
            return None
        text = normalize_space(text)
        found = {
            (int(day), self.months[month.lower()], int(year) if year else None)
            for day, month, year in self._date_re.findall(text)
        }
        if len(found) != 1:
            logger.warning(f"Date {text!r} has {'no' if not found else 'more than one'} date, so it was not parsed.")
            return None
        day, month, year = found.pop()
        if year is not None:
            # Full dates are parsed by amazon-orders, which validates them strictly
            parsed: date | None = self.amazon_locale.parse_date(text)
            return DateParts(parsed.day, parsed.month, parsed.year) if parsed else None
        if not 1 <= day <= 31:
            logger.warning(f"Date {text!r} is not a valid date, so it was not parsed.")
            return None
        return DateParts(day, month)

    def parse_quantity_interval(self, text: str | None, warn: bool = True) -> tuple[int, Interval] | None:
        """Parse quantity and interval such as ``3 Einheiten alle 2 Monate``."""
        match = self.QUANTITY_INTERVAL_RE.fullmatch(normalize_space(text or ""))
        if not match:
            if text and warn:
                logger.warning(f"Quantity and interval {text!r} were not recognized, so they were not parsed.")
            return None
        quantity, every, unit = match.groups()
        return int(quantity), Interval(int(every or 1), self.INTERVAL_UNITS[unit.lower()])

    def parse_discount_percent(self, text: str | None) -> int | None:
        match = self.DISCOUNT_PERCENT_RE.search(normalize_space(text or ""))
        return int(match.group(1)) if match else None

    def parse_item_count(self, text: str | None) -> int | None:
        match = self.ITEM_COUNT_RE.search(normalize_space(text or ""))
        return int(match.group(1)) if match else None

    def parse_savings(self, text: str | None) -> Decimal | None:
        match = self.SAVINGS_RE.search(normalize_space(text or ""))
        return self.parse_amount(match.group(1)) if match else None

    def parse_unit_price(self, text: str | None) -> tuple[Decimal, str] | None:
        """Parse a unit price such as ``24,99 € pro l`` into amount and unit."""
        match = self.UNIT_PRICE_RE.fullmatch(normalize_space(html.unescape(text or "")))
        if not match:
            if text:
                logger.warning(f"Unit price {text!r} was not recognized, so it was not parsed.")
            return None
        amount = self.parse_amount(match.group(1))
        return (amount, match.group(2)) if amount is not None else None

    def list_price_type_of(self, label: str | None) -> ListPriceType | None:
        """The type of a list price by its label, ``None`` if the label is not one of a list price."""
        label = normalize_space(label or "").lower()
        for prefix, list_price_type in self.LIST_PRICE_TYPES.items():
            if label.startswith(prefix.lower()):
                return list_price_type
        return None

    def is_alternative_offers_caption(self, text: str | None) -> bool:
        text = normalize_space(text or "").lower()
        return any(text.startswith(caption.lower()) for caption in self.ALTERNATIVE_OFFERS_CAPTIONS)

    def is_this_item_label(self, text: str | None) -> bool:
        return normalize_space(text or "").lower().startswith(self.THIS_ITEM_LABEL.lower())

    def status_of(self, text: str) -> SubscriptionStatus:
        """The status of a subscription tile's status text."""
        for prefix, status in self.STATUS_TEXTS.items():
            if normalize_space(text).lower().startswith(prefix.lower()):
                return status
        logger.warning(f"Subscription status {text!r} is not known, so it was not parsed.")
        return SubscriptionStatus.UNKNOWN

    def is_substitute_alert(self, text: str) -> bool:
        return any(alert.lower() in normalize_space(text).lower() for alert in self.SUBSTITUTE_ALERT_TEXTS)
