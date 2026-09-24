from decimal import Decimal

import pytest

from amazon_subscriptions.dates import DateParts
from amazon_subscriptions.exceptions import SubscriptionsError
from amazon_subscriptions.locales import get_locale
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.locales.de import DeSubscriptionLocale
from amazon_subscriptions.models import Interval, IntervalUnit, ListPriceType, SubscriptionStatus


@pytest.mark.parametrize("domain", ["amazon.de", "www.amazon.de", "https://www.amazon.de/auto-deliveries"])
def test_get_locale(domain: str) -> None:
    assert isinstance(get_locale(domain), DeSubscriptionLocale)


def test_get_locale_unsupported() -> None:
    with pytest.raises(SubscriptionsError):
        get_locale("amazon.co.jp")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("6,76€", Decimal("6.76")),
        ("6,76 €", Decimal("6.76")),
        ("1.234,5 €", Decimal("1234.5")),
        ("12 EUR", Decimal("12.0")),
        ("-0,99\xa0€", Decimal("-0.99")),
        (None, None),
        ("", None),
    ],
)
def test_parse_amount(de: SubscriptionLocale, text: str | None, expected: Decimal | None) -> None:
    assert de.parse_amount(text) == expected


@pytest.mark.parametrize("text", ["6.76 €", "ca. 6,76 €", "1,234"])
def test_parse_amount_unknown_format(de: SubscriptionLocale, text: str, caplog: pytest.LogCaptureFixture) -> None:
    assert de.parse_amount(text) is None
    assert "not recognized" in caplog.text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nächste Lieferung: 1. Okt.", DateParts(1, 10)),
        ("Ankunft: Do., 1. Okt.", DateParts(1, 10)),
        ("Letzter Tag zum Bearbeiten von Sa., 26. Sept.", DateParts(26, 9)),
        ("26. September", DateParts(26, 9)),
        ("1.\xa0März", DateParts(1, 3)),
        ("1. Oktober 2026", DateParts(1, 10, 2026)),
    ],
)
def test_parse_date_parts(de: SubscriptionLocale, text: str, expected: DateParts) -> None:
    assert de.parse_date_parts(text) == expected


@pytest.mark.parametrize("text", ["Nächste Lieferung: bald", "1. Okt. oder 2. Okt.", "32. Okt.", "1. Oktobär"])
def test_parse_date_parts_unknown(de: SubscriptionLocale, text: str, caplog: pytest.LogCaptureFixture) -> None:
    assert de.parse_date_parts(text) is None
    assert caplog.records


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 Einheit jeden Monat", (1, Interval(1, IntervalUnit.MONTH))),
        ("3 Einheiten alle 2 Monate", (3, Interval(2, IntervalUnit.MONTH))),
        ("2 Einheiten alle 6 Wochen", (2, Interval(6, IntervalUnit.WEEK))),
        ("1 Einheit jede Woche", (1, Interval(1, IntervalUnit.WEEK))),
    ],
)
def test_parse_quantity_interval(de: SubscriptionLocale, text: str, expected: tuple[int, Interval]) -> None:
    assert de.parse_quantity_interval(text) == expected


def test_parse_quantity_interval_unknown(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture) -> None:
    assert de.parse_quantity_interval("1 Einheit ab und zu") is None
    assert "not recognized" in caplog.text


def test_parse_delivery_texts(de: SubscriptionLocale) -> None:
    assert de.parse_discount_percent("Spare 15 %") == 15
    assert de.parse_discount_percent("Spare 5%") == 5
    assert de.parse_item_count("11 Artikel") == 11
    assert de.parse_savings("🥳 Ersparnis 25,32 € \u2013 Maximale Einsparungen freigeschaltet") == Decimal("25.32")
    assert de.parse_savings("Maximale Einsparungen freigeschaltet") is None


def test_status_of_unknown_text(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture) -> None:
    assert de.status_of("Irgendein Hinweis") == SubscriptionStatus.UNKNOWN
    assert "not known" in caplog.text


def test_is_substitute_alert(de: SubscriptionLocale) -> None:
    assert de.is_substitute_alert("Backup-Produkt wird versendet")
    assert not de.is_substitute_alert("Preis geändert")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("24,99&nbsp;&euro; pro l", (Decimal("24.99"), "l")),
        ("0,25 € pro Stück", (Decimal("0.25"), "Stück")),
        ("1.234,50 € pro 100 ml", (Decimal("1234.50"), "100 ml")),
        (None, None),
    ],
)
def test_parse_unit_price(de: SubscriptionLocale, text: str | None, expected: tuple[Decimal, str] | None) -> None:
    assert de.parse_unit_price(text) == expected


def test_parse_unit_price_unknown_format(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture) -> None:
    assert de.parse_unit_price("24,99 € je Liter") is None
    assert "not recognized" in caplog.text


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("UVP:", ListPriceType.UVP),
        (" uvp: ", ListPriceType.UVP),
        ("Niedrigster Preis in 30 Tagen:", ListPriceType.LOWEST_30D),
        ("Statt:", ListPriceType.WAS),
        ("Einmaliger Preis:", None),
        (None, None),
    ],
)
def test_list_price_type_of(de: SubscriptionLocale, label: str | None, expected: ListPriceType | None) -> None:
    assert de.list_price_type_of(label) is expected


def test_is_alternative_offers_caption(de: SubscriptionLocale) -> None:
    assert de.is_alternative_offers_caption(" Alternative Angebote ")
    assert not de.is_alternative_offers_caption("Einmaliger Kauf")
    assert not de.is_alternative_offers_caption(None)


def test_is_this_item_label(de: SubscriptionLocale) -> None:
    assert de.is_this_item_label("Dieser Artikel:")
    assert not de.is_this_item_label("Pritt Klebestift")
    assert not de.is_this_item_label(None)
