from datetime import date

from amazon_subscriptions import dates
from amazon_subscriptions.dates import DateParts

TODAY = date(2026, 9, 24)


def test_next_delivery_later_this_year() -> None:
    assert dates.next_delivery(1, 10, TODAY) == date(2026, 10, 1)


def test_next_delivery_next_year() -> None:
    assert dates.next_delivery(1, 1, TODAY) == date(2027, 1, 1)
    assert dates.next_delivery(1, 2, TODAY) == date(2027, 2, 1)


def test_next_delivery_within_grace_period() -> None:
    # A delivery that is late or on its way stays in the current year
    assert dates.next_delivery(1, 9, TODAY) == date(2026, 9, 1)
    assert dates.next_delivery(24, 8, TODAY) == date(2027, 8, 24)


def test_last_on_or_before() -> None:
    assert dates.last_on_or_before(26, 9, date(2026, 10, 1)) == date(2026, 9, 26)
    assert dates.last_on_or_before(28, 12, date(2027, 1, 1)) == date(2026, 12, 28)


def test_nearest() -> None:
    assert dates.nearest(1, 1, date(2026, 12, 31)) == date(2027, 1, 1)
    assert dates.nearest(31, 12, date(2027, 1, 1)) == date(2026, 12, 31)


def test_29_february() -> None:
    assert dates.next_delivery(29, 2, date(2027, 12, 1)) == date(2028, 2, 29)
    # Not within a year, so it cannot be a next delivery
    assert dates.next_delivery(29, 2, TODAY) is None


def test_resolve() -> None:
    def resolver(day: int, month: int) -> date:
        return date(2000, month, day)

    assert dates.resolve(None, resolver) is None
    assert dates.resolve(DateParts(1, 10, 2026), resolver) == date(2026, 10, 1)
    assert dates.resolve(DateParts(1, 10), resolver) == date(2000, 10, 1)
