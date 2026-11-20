"""Resolve the year of dates that Amazon renders without one (e.g. "1. Okt.").

The year is never guessed from the text. It follows from a reference date that is known to be close, with a rule
per kind of date:

* a next delivery lies in the future, so it is the first occurrence on or after the reference date (minus a grace
  period for deliveries that are late or on their way),
* a change deadline lies before its delivery, so it is the last occurrence on or before the delivery date,
* a date next to a precise timestamp is the occurrence nearest to that timestamp.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

#: A next delivery date may lie up to this many days before the reference date, e.g. while it is on its way.
NEXT_DELIVERY_GRACE_DAYS = 30


@dataclass(frozen=True)
class DateParts:
    """A date as rendered, which may lack the year."""

    day: int
    month: int
    year: int | None = None


def resolve(parts: DateParts | None, resolve_year: Callable[[int, int], date | None]) -> date | None:
    """The date of the parts, using ``resolve_year(day, month)`` if they have no year."""
    if parts is None:
        return None
    if parts.year is not None:
        return date(parts.year, parts.month, parts.day)
    return resolve_year(parts.day, parts.month)


def _occurrence(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:  # e.g. 29 February
        return None


def _candidates(day: int, month: int, reference: date) -> list[date]:
    candidates = (_occurrence(year, month, day) for year in (reference.year - 1, reference.year, reference.year + 1))
    return [candidate for candidate in candidates if candidate is not None]


def first_on_or_after(day: int, month: int, not_before: date) -> date | None:
    return min((c for c in _candidates(day, month, not_before) if c >= not_before), default=None)


def last_on_or_before(day: int, month: int, not_after: date) -> date | None:
    return max((c for c in _candidates(day, month, not_after) if c <= not_after), default=None)


def nearest(day: int, month: int, reference: date) -> date | None:
    return min(_candidates(day, month, reference), key=lambda c: abs(c - reference), default=None)


def next_delivery(day: int, month: int, today: date) -> date | None:
    return first_on_or_after(day, month, today - timedelta(days=NEXT_DELIVERY_GRACE_DAYS))
