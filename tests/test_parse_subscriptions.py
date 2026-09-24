from datetime import date

import pytest

from amazon_subscriptions.exceptions import CaptchaError, PageStructureError, SessionExpiredError
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.models import Interval, IntervalUnit, Subscription, SubscriptionStatus
from amazon_subscriptions.parse import parse_subscriptions, parse_subscriptions_next_url
from tests.conftest import DE_TODAY, read_fixture


@pytest.fixture(scope="module")
def subscriptions(de: SubscriptionLocale) -> list[Subscription]:
    landing = parse_subscriptions(read_fixture("de/landing.html"), de, DE_TODAY)
    page_2 = parse_subscriptions(read_fixture("de/subscriptions-page-2.html"), de, DE_TODAY)
    assert len(landing) == 30
    assert len(page_2) == 2
    return landing + page_2


def test_all_subscriptions(subscriptions: list[Subscription]) -> None:
    assert len(subscriptions) == 32
    assert len({s.subscription_id for s in subscriptions}) == 32
    for subscription in subscriptions:
        assert subscription.subscription_id.startswith(("SNST0_", "SNSA0_", "SNSD0_"))
        assert subscription.asin
        assert subscription.product_url == f"/dp/{subscription.asin}"
        assert subscription.title and subscription.title.startswith("Testartikel ")
        assert subscription.image_url
        assert subscription.quantity
        assert subscription.interval
        assert subscription.interval.unit == IntervalUnit.MONTH
        assert subscription.next_delivery_date
        assert subscription.status == SubscriptionStatus.ACTIVE
        assert subscription.raw_status_text is None
        assert subscription.currency == "EUR"
        # Not shown on the subscriptions page
        assert subscription.price is subscription.list_price is subscription.subscription_price is None


def test_first_subscription(subscriptions: list[Subscription]) -> None:
    first = subscriptions[0]
    assert first.asin == "B0TEST0024"
    assert first.title and first.title.startswith("Testartikel 01 ")
    assert first.quantity == 1
    assert first.interval == Interval(1, IntervalUnit.MONTH)
    assert first.next_delivery_date == date(2026, 10, 1)


def test_quantities_and_intervals(subscriptions: list[Subscription]) -> None:
    by_asin = {s.asin: s for s in subscriptions}
    assert by_asin["B0TEST0025"].interval == Interval(5, IntervalUnit.MONTH)
    assert by_asin["B0TEST0029"].quantity == 3
    assert by_asin["B0TEST0032"].quantity == 2


def test_next_delivery_year_rollover(subscriptions: list[Subscription]) -> None:
    next_dates = {s.next_delivery_date for s in subscriptions}
    assert next_dates == {date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)}


def test_next_url() -> None:
    next_url = parse_subscriptions_next_url(read_fixture("de/landing.html"))
    assert next_url and "/replenishment/subscriptions" in next_url
    assert parse_subscriptions_next_url(read_fixture("de/subscriptions-page-2.html")) is None


def test_unknown_page(de: SubscriptionLocale) -> None:
    with pytest.raises(PageStructureError, match=r"No subscriptions found.*\(page: x\.html\)"):
        parse_subscriptions("<html><body><p>Neue Seite</p></body></html>", de, DE_TODAY, page="x.html")


def test_delivery_page_is_no_subscriptions_page(de: SubscriptionLocale) -> None:
    with pytest.raises(PageStructureError):
        parse_subscriptions(read_fixture("de/delivery-1.html"), de, DE_TODAY)


def test_captcha(de: SubscriptionLocale) -> None:
    html = '<form action="/errors/validateCaptcha"><input id="captchacharacters"></form>'
    with pytest.raises(CaptchaError):
        parse_subscriptions(html, de, DE_TODAY)


def test_sign_in(de: SubscriptionLocale) -> None:
    html = '<form name="signIn"><input id="ap_email"></form>'
    with pytest.raises(SessionExpiredError, match="expired"):
        parse_subscriptions(html, de, DE_TODAY)


def test_unknown_status_text(de: SubscriptionLocale, caplog: pytest.LogCaptureFixture) -> None:
    html = """
    <div data-edit-url="/edit?subscriptionId=SNST0_TEST0001&amp;subAsin=B0TEST9999">
      <img src="https://example.com/x.jpg" alt="Testartikel 99">
      <span class="a-truncate-full">Testartikel 99 lorem ipsum</span>
      <span>Derzeit nicht verfügbar</span>
      <span>1 Einheit jeden Monat</span>
      <a>Abo verwalten</a>
    </div>
    """
    [subscription] = parse_subscriptions(html, de, DE_TODAY)
    assert subscription.subscription_id == "SNST0_TEST0001"
    assert subscription.title == "Testartikel 99 lorem ipsum"
    assert subscription.next_delivery_date is None
    assert subscription.status == SubscriptionStatus.UNKNOWN
    assert subscription.raw_status_text == "Derzeit nicht verfügbar"
    assert "not known" in caplog.text
