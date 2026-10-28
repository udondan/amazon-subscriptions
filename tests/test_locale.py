from decimal import Decimal

import pytest
from amazonorders.region_data import REGION_SITES

from amazon_subscriptions.dates import DateParts
from amazon_subscriptions.exceptions import SubscriptionsError
from amazon_subscriptions.locales import SITE_CURRENCIES, get_locale
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.locales.en import EnglishSubscriptionLocale
from amazon_subscriptions.models import Interval, IntervalUnit, ListPriceType, SubscriptionStatus


@pytest.mark.parametrize("domain", ["amazon.de", "www.amazon.de", "https://www.amazon.de/auto-deliveries"])
def test_get_locale(domain: str) -> None:
    site_locale = get_locale(domain)
    assert isinstance(site_locale, EnglishSubscriptionLocale)
    assert site_locale.currency == "EUR"


@pytest.mark.parametrize(
    ("domain", "currency"),
    [("amazon.com", "USD"), ("amazon.co.uk", "GBP"), ("amazon.ca", "CAD"), ("amazon.co.jp", "JPY")],
)
def test_get_locale_currency(domain: str, currency: str) -> None:
    assert get_locale(domain).currency == currency


def test_get_locale_unknown() -> None:
    with pytest.raises(SubscriptionsError, match="not a known"):
        get_locale("amazon.example")


def test_get_locale_without_english() -> None:
    with pytest.raises(SubscriptionsError, match="English"):
        get_locale("amazon.com.br")


def test_get_locale_not_amazon() -> None:
    with pytest.raises(SubscriptionsError):
        get_locale("example.com")


def test_site_currencies_cover_english_sites() -> None:
    english = {tld for tld, site in REGION_SITES.items() if site.english_locale}
    assert english <= SITE_CURRENCIES.keys()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("€6.76", Decimal("6.76")),
        ("€ 6.76", Decimal("6.76")),
        ("€1,234.5", Decimal("1234.5")),
        ("€1,234,567.89", Decimal("1234567.89")),
        ("12 EUR", Decimal("12.0")),
        ("12.34 EUR", Decimal("12.34")),
        ("-€0.99", Decimal("-0.99")),
        ("-0.99\xa0€", Decimal("-0.99")),
        (None, None),
        ("", None),
    ],
)
def test_parse_amount(de: SubscriptionLocale, text: str | None, expected: Decimal | None) -> None:
    assert de.parse_amount(text) == expected


@pytest.mark.parametrize("text", ["1.234,56 €", "6,76 €", "approx. €6.76", "1,23"])
def test_parse_amount_unknown_format(de: SubscriptionLocale, text: str, caplog: pytest.LogCaptureFixture) -> None:
    assert de.parse_amount(text) is None
    assert "not recognized" in caplog.text


def test_parse_amount_dollar() -> None:
    assert get_locale("amazon.com").parse_amount("$1,234.56") == Decimal("1234.56")
    assert get_locale("amazon.co.uk").parse_amount("£12.99") == Decimal("12.99")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Next delivery: 1 Nov", DateParts(1, 11)),
        ("Arriving Tue, 1 Dec", DateParts(1, 12)),
        ("Arriving 1 December", DateParts(1, 12)),
        ("Last day to edit Tue, 27 Oct", DateParts(27, 10)),
        ("26 Sept", DateParts(26, 9)),
        ("1st October 2026", DateParts(1, 10, 2026)),
        ("Thu, 1 October 2026", DateParts(1, 10, 2026)),
        ("1\xa0Mar", DateParts(1, 3)),
        # Month first, as amazon.com shows them
        ("Next delivery: Nov 1", DateParts(1, 11)),
        ("Arriving Tue, Dec 1", DateParts(1, 12)),
        ("October 1, 2026", DateParts(1, 10, 2026)),
        ("Sept 26th", DateParts(26, 9)),
        ("29 Feb", DateParts(29, 2)),
    ],
)
def test_parse_date_parts(de: SubscriptionLocale, text: str, expected: DateParts) -> None:
    assert de.parse_date_parts(text) == expected


@pytest.mark.parametrize(
    "text", ["Next delivery: soon", "1 Oct or 2 Oct", "32 Oct", "1 Octember", "Oct 32", "30 Feb", "1 Nov 2 Dec"]
)
def test_parse_date_parts_unknown(de: SubscriptionLocale, text: str, caplog: pytest.LogCaptureFixture) -> None:
    assert de.parse_date_parts(text) is None
    assert caplog.records


def test_parse_date_parts_ignores_numbers_after_the_date(de: SubscriptionLocale) -> None:
    # "Oct 12" would be a date too, the date that starts first wins
    assert de.parse_date_parts("5 Oct 12 units") == DateParts(5, 10)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 unit every 1 month", (1, Interval(1, IntervalUnit.MONTH))),
        ("3 units every 2 months", (3, Interval(2, IntervalUnit.MONTH))),
        ("2 units every 6 weeks", (2, Interval(6, IntervalUnit.WEEK))),
        ("1 unit every week", (1, Interval(1, IntervalUnit.WEEK))),
        ("1 unit every 10 days", (1, Interval(10, IntervalUnit.DAY))),
    ],
)
def test_parse_quantity_interval(de: SubscriptionLocale, text: str, expected: tuple[int, Interval]) -> None:
    assert de.parse_quantity_interval(text) == expected


def test_parse_quantity_interval_unknown(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture) -> None:
    assert de.parse_quantity_interval("1 unit now and then") is None
    assert "not recognized" in caplog.text


def test_parse_delivery_texts(de: SubscriptionLocale) -> None:
    assert de.parse_discount_percent("Saving 15%") == 15
    assert de.parse_discount_percent("Saving 5 %") == 5
    assert de.parse_item_count("11 items") == 11
    assert de.parse_item_count("1 item") == 1
    assert de.parse_savings("🥳 Saving €10.58 - Max savings unlocked") == Decimal("10.58")
    assert de.parse_savings("Saving €1,234.56") == Decimal("1234.56")
    assert de.parse_savings("🥳 Max savings unlocked") is None
    # The discount of an item is no amount
    assert de.parse_savings("Saving 15%") is None


def test_status_of_unknown_text(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture) -> None:
    assert de.status_of("Some notice") == SubscriptionStatus.UNKNOWN
    assert "not known" in caplog.text


def test_is_substitute_alert(de: SubscriptionLocale) -> None:
    assert de.is_substitute_alert("Backup product will be shipped")
    assert de.is_substitute_alert(" backup product  will be shipped. ")
    assert not de.is_substitute_alert("Temporarily Unavailable")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("&euro;24.99 per l", (Decimal("24.99"), "l")),
        ("€0.25 per count", (Decimal("0.25"), "count")),
        ("€1,234.50 per 100 ml", (Decimal("1234.50"), "100 ml")),
        (None, None),
    ],
)
def test_parse_unit_price(de: SubscriptionLocale, text: str | None, expected: tuple[Decimal, str] | None) -> None:
    assert de.parse_unit_price(text) == expected


def test_parse_unit_price_unknown_format(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture) -> None:
    assert de.parse_unit_price("€24.99 for each litre") is None
    assert "not recognized" in caplog.text


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("RRP:", ListPriceType.RRP),
        (" rrp: ", ListPriceType.RRP),
        ("Was:", ListPriceType.WAS),
        ("One-time purchase:", None),
        (None, None),
    ],
)
def test_list_price_type_of(de: SubscriptionLocale, label: str | None, expected: ListPriceType | None) -> None:
    assert de.list_price_type_of(label) is expected


def test_is_alternative_offers_caption(de: SubscriptionLocale) -> None:
    assert de.is_alternative_offers_caption("Another way to buy")
    assert de.is_alternative_offers_caption("  another way to buy ")
    assert not de.is_alternative_offers_caption("One-time purchase")
    assert not de.is_alternative_offers_caption(None)


def test_is_this_item_label(de: SubscriptionLocale) -> None:
    assert de.is_this_item_label("This item: Product 01")
    assert not de.is_this_item_label("Product 01")
    assert not de.is_this_item_label(None)
