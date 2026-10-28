import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from bs4 import BeautifulSoup

from amazon_subscriptions.client import SubscriptionsClient
from amazon_subscriptions.exceptions import (
    CaptchaError,
    PageStructureError,
    SessionExpiredError,
    SubscriptionsError,
)
from amazon_subscriptions.models import ListPriceSource, ListPriceType
from amazon_subscriptions.parse import parse_acp_widget, selectors
from tests.conftest import (
    DE_BASE_URL,
    DE_DELIVERIES_PAGINATE_URL,
    DE_DELIVERY_1_URL,
    DE_DETAIL_URL,
    DE_LANDING_URL,
    DE_PRODUCT_URL,
    DE_SUBSCRIPTIONS_NEXT_URL,
    DE_SUBSCRIPTIONS_PAGINATE_URL,
    DE_TODAY,
    delivery_1_without_date,
    make_session,
    read_fixture,
    register_broken_delivery_1,
    register_de_pages,
    register_de_product_pages,
    register_delivery_1_with_backup_product,
    register_subscriptions_next_page,
    subscriptions_page_2,
    substitute_item_title,
    with_subscriptions_next_page,
)

DELIVERIES = [(date(2026, 11, 1), 11, None), (date(2026, 12, 1), 17, None)]


def make_client(tmp_path: Path, **kwargs: object) -> SubscriptionsClient:
    return SubscriptionsClient(make_session(tmp_path, **kwargs), today=DE_TODAY)


def test_loads_subscriptions_and_deliveries(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    client = make_client(tmp_path)

    subscriptions = client.get_subscriptions()
    deliveries = client.get_upcoming_deliveries()

    assert len(subscriptions) == 30
    assert len({s.subscription_id for s in subscriptions}) == 30
    assert all(s.next_delivery_date for s in subscriptions)
    assert all(s.product_url and s.product_url.startswith(f"{DE_BASE_URL}/dp/B0TEST") for s in subscriptions)

    assert [(d.date, len(d.items), d.total) for d in deliveries] == DELIVERIES
    for delivery in deliveries:
        assert delivery.url and delivery.url.startswith(f"{DE_LANDING_URL}/?")
        assert delivery.delivery_bundle_id
        assert all(item.subscription_id for item in delivery.items)
    assert any(s.subscription_price is not None for s in subscriptions)

    # Both results come from one load of the pages
    assert [(c.request.method, urlparse(c.request.url).path) for c in mock.calls] == [
        ("GET", "/auto-deliveries"),
        # The next page of deliveries, which is empty
        ("POST", urlparse(mock.calls[1].request.url).path),
        ("GET", "/auto-deliveries/"),
        ("GET", "/auto-deliveries/"),
    ]
    assert DE_DELIVERIES_PAGINATE_URL.fullmatch(mock.calls[1].request.url or "")
    # Product pages are only loaded with ``with_prices``
    assert all(s.price is None and s.unit_price is None for s in subscriptions)


def test_with_prices(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    register_de_product_pages(mock)
    subscriptions = SubscriptionsClient(make_session(tmp_path), today=DE_TODAY, with_prices=True).get_subscriptions()

    product_calls = [c for c in mock.calls if DE_PRODUCT_URL.fullmatch(c.request.url or "")]
    assert len(product_calls) == len(subscriptions) == 30
    by_asin = {s.asin: s for s in subscriptions}
    rrp, was, other = by_asin["B0TEST0024"], by_asin["B0TEST0042"], by_asin["B0TEST0026"]
    assert (rrp.price, rrp.list_price, rrp.list_price_type, rrp.list_price_source) == (
        Decimal("8.69"),
        Decimal("11.99"),
        ListPriceType.RRP,
        ListPriceSource.BUYBOX,
    )
    assert (rrp.unit_price, rrp.unit_price_unit) == (Decimal("57.93"), "l")
    assert (was.price, was.list_price, was.list_price_type) == (Decimal("6.13"), Decimal("6.45"), ListPriceType.WAS)
    assert (other.price, other.list_price, other.unit_price, other.unit_price_unit) == (
        Decimal("12.99"),
        None,
        Decimal("133.92"),
        "kg",
    )
    single_offer = by_asin["B0TEST0045"]
    assert (single_offer.price, single_offer.unit_price, single_offer.unit_price_unit) == (
        Decimal("56.48"),
        Decimal("9.41"),
        "count",
    )
    for asin in ["B0TEST0044", "B0TEST0049"]:
        assert (by_asin[asin].price, by_asin[asin].list_price, by_asin[asin].unit_price) == (None, None, None)
    assert all(s.alternative_offer is None for s in subscriptions)
    assert all(not s.parse_errors for s in subscriptions)


def test_with_prices_captcha_stops_loading_product_pages(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    mock.get(DE_PRODUCT_URL, body='<html><body><form action="/errors/validateCaptcha"></form></body></html>')
    client = SubscriptionsClient(make_session(tmp_path), today=DE_TODAY, with_prices=True)
    subscriptions = client.get_subscriptions()

    assert len(subscriptions) == 30
    assert all(s.price is None for s in subscriptions)
    # A captcha is not retried
    assert len([c for c in mock.calls if DE_PRODUCT_URL.fullmatch(c.request.url or "")]) == 1
    [error] = client.errors
    assert "captcha" in error.message
    assert [s.parse_errors for s in subscriptions if s.parse_errors] == [[error]]


def test_with_prices_product_page_error(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    mock.get(f"{DE_BASE_URL}/dp/B0TEST0024", status=404)
    mock.get(f"{DE_BASE_URL}/dp/B0TEST0024", status=404)
    register_de_product_pages(mock)
    client = SubscriptionsClient(make_session(tmp_path), today=DE_TODAY, with_prices=True)
    subscriptions = client.get_subscriptions()

    by_asin = {s.asin: s for s in subscriptions}
    assert by_asin["B0TEST0024"].price is None
    assert by_asin["B0TEST0026"].price == Decimal("12.99")
    [error] = by_asin["B0TEST0024"].parse_errors
    assert error.url == f"{DE_BASE_URL}/dp/B0TEST0024"
    assert "404" in error.message
    assert error.html_path is None
    assert client.errors == [error]
    assert all(not s.parse_errors for s in subscriptions if s.asin != "B0TEST0024")


def test_with_prices_product_page_error_once(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    mock.get(f"{DE_BASE_URL}/dp/B0TEST0024", status=503)
    register_de_product_pages(mock)
    client = SubscriptionsClient(make_session(tmp_path), today=DE_TODAY, with_prices=True)
    subscriptions = client.get_subscriptions()

    assert {s.asin: s for s in subscriptions}["B0TEST0024"].price == Decimal("8.69")
    assert client.errors == []
    assert len([c for c in mock.calls if c.request.url == f"{DE_BASE_URL}/dp/B0TEST0024"]) == 2


def test_delivery_page_without_date(tmp_path: Path, mock: responses.RequestsMock, failed_dir: Path) -> None:
    register_broken_delivery_1(mock)
    register_de_pages(mock)
    client = make_client(tmp_path)
    deliveries = client.get_upcoming_deliveries()
    subscriptions = client.get_subscriptions()

    # The delivery is complete, with the date of its URL
    assert [(d.date, len(d.items), d.total) for d in deliveries] == DELIVERIES
    assert all(item.subscription_id for d in deliveries for item in d.items)
    # Loaded once more, not more often
    assert len([c for c in mock.calls if DE_DELIVERY_1_URL.fullmatch(c.request.url or "")]) == 2

    [error] = deliveries[0].parse_errors
    assert error.url == deliveries[0].url
    assert error.selector == selectors.DELIVERY_DATE
    assert "taken from the URL" in error.message
    assert deliveries[1].parse_errors == []
    assert client.errors == [error]
    # The subscriptions of the delivery have the error too
    assert all(s.parse_errors == [error] for s in subscriptions if s.next_delivery_date == date(2026, 11, 1))
    assert all(not s.parse_errors for s in subscriptions if s.next_delivery_date != date(2026, 11, 1))

    # Both attempts are saved, the error names the last one
    saved = sorted(failed_dir.iterdir())
    assert [p.name.split("_", 1)[1] for p in saved] == ["delivery-2026-11-01_1.html", "delivery-2026-11-01_2.html"]
    assert error.html_path == str(saved[1])
    assert saved[1].read_text(encoding="utf-8") == delivery_1_without_date()


def test_delivery_page_without_date_once(tmp_path: Path, mock: responses.RequestsMock, failed_dir: Path) -> None:
    register_broken_delivery_1(mock, times=1)
    register_de_pages(mock)
    client = make_client(tmp_path)
    deliveries = client.get_upcoming_deliveries()

    assert client.errors == []
    assert all(not d.parse_errors for d in deliveries)
    assert len([c for c in mock.calls if DE_DELIVERY_1_URL.fullmatch(c.request.url or "")]) == 2
    assert [p.name.split("_", 1)[1] for p in failed_dir.iterdir()] == ["delivery-2026-11-01_1.html"]


def test_delivery_page_error_falls_back_to_the_card(
    tmp_path: Path, mock: responses.RequestsMock, failed_dir: Path
) -> None:
    mock.get(DE_DELIVERY_1_URL, status=500, body="")
    mock.get(DE_DELIVERY_1_URL, body="<html><body>Something new</body></html>")
    register_de_pages(mock)
    client = make_client(tmp_path)
    deliveries = client.get_upcoming_deliveries()

    first = deliveries[0]
    assert (first.date, first.change_deadline, first.items, first.total) == (
        date(2026, 11, 1),
        date(2026, 10, 27),
        [],
        None,
    )
    assert first.discount_tier.item_count == 11
    assert first.delivery_bundle_id and first.url and DE_DELIVERY_1_URL.fullmatch(first.url)
    [error] = first.parse_errors
    assert error.selector == selectors.DELIVERY_ITEM
    assert error.message == f"No delivery items found ({selectors.DELIVERY_ITEM!r})"
    # Only the second attempt received a page
    assert error.html_path and error.html_path.endswith("_delivery-2026-11-01_2.html")
    assert len(list(failed_dir.iterdir())) == 1
    assert len(deliveries[1].items) == 17


def test_delivery_page_captcha(tmp_path: Path, mock: responses.RequestsMock) -> None:
    mock.get(DE_DELIVERY_1_URL, body='<form action="/errors/validateCaptcha"></form>')
    register_de_pages(mock)
    client = make_client(tmp_path)
    deliveries = client.get_upcoming_deliveries()

    # The captcha is not retried, and no further delivery page is requested
    assert [urlparse(c.request.url).path for c in mock.calls[2:]] == ["/auto-deliveries/"]
    assert [(d.date, d.items) for d in deliveries] == [(date(2026, 11, 1), []), (date(2026, 12, 1), [])]
    assert len(client.errors) == 2
    assert all("captcha" in e.message for e in client.errors)


@pytest.mark.usefixtures("substitute")
def test_substitute_asin(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    [substitute] = [item for d in deliveries for item in d.items if item.substitute]
    assert substitute.asin == "B0TEST0024"
    assert substitute.substitute_asin == "B0TEST0054"
    assert all(item.substitute_asin is None for d in deliveries for item in d.items if not item.substitute)
    [request] = [c.request for c in mock.calls if DE_DETAIL_URL.fullmatch(c.request.url or "")]
    assert parse_qs(urlparse(request.url).query) == {
        "subscriptionId": ["SNST0_5969B1ECB08E99CAC41C"],
        "subAsin": ["B0TEST0024"],
        "enableMydExperience": ["1"],
        "clientName": ["mydHub"],
    }


def test_substitute_with_other_backup_product(
    tmp_path: Path, mock: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    # The detail sheet names a backup product with another title than the item
    register_delivery_1_with_backup_product(mock)
    register_de_pages(mock)

    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    assert all(item.substitute_asin is None for d in deliveries for item in d.items)
    assert f"is not the item {substitute_item_title()!r}" in caplog.text


@pytest.mark.usefixtures("substitute")
def test_substitute_detail_sheet_error(
    tmp_path: Path, mock: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock.replace(responses.GET, DE_DETAIL_URL, status=500, body="")
    register_de_pages(mock)

    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    assert all(item.substitute_asin is None for d in deliveries for item in d.items)
    assert "was not loaded" in caplog.text


@pytest.mark.usefixtures("substitute")
def test_substitute_detail_sheet_captcha(tmp_path: Path, mock: responses.RequestsMock) -> None:
    mock.replace(responses.GET, DE_DETAIL_URL, body='<form action="/errors/validateCaptcha"></form>')
    register_de_pages(mock)
    register_de_product_pages(mock)
    client = SubscriptionsClient(make_session(tmp_path), today=DE_TODAY, with_prices=True)
    deliveries = client.get_upcoming_deliveries()

    assert all(item.substitute_asin is None for d in deliveries for item in d.items)
    # No product page is requested after the captcha
    assert not [c for c in mock.calls if DE_PRODUCT_URL.fullmatch(c.request.url or "")]
    # The prices are incomplete, noted on the first subscription whose product page was not requested
    [error] = client.errors
    assert "captcha" in error.message and DE_PRODUCT_URL.fullmatch(error.url or "")


def test_next_page_is_requested_like_the_browser(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_subscriptions_next_page(mock)
    subscriptions = make_client(tmp_path).get_subscriptions()

    assert len(subscriptions) == 32
    assert [s.asin for s in subscriptions[-2:]] == ["B0TEST0091", "B0TEST0092"]
    widget = parse_acp_widget(mock.calls[0].response.text, selectors.SUBSCRIPTIONS_NEXT_PAGE)
    assert widget is not None
    request = mock.calls[1].request
    assert DE_SUBSCRIPTIONS_PAGINATE_URL.fullmatch(request.url or "")
    assert urlparse(request.url).path == f"{widget.path}paginate"
    assert parse_qs(urlparse(request.url).query) == {
        "page-type": ["RCXSubs"],
        "pf_rd_p": [widget.tracking["pf_rd_p"]],
        "pf_rd_r": [widget.tracking["pf_rd_r"]],
        "stamp": [widget.stamp],
    }
    assert json.loads(request.body or "") == {"nextUrl": DE_SUBSCRIPTIONS_NEXT_URL}
    headers = request.headers
    assert headers["x-amz-acp-params"] == widget.params
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "text/html, application/json"
    assert headers["Origin"] == DE_BASE_URL
    assert headers["Referer"] == DE_LANDING_URL
    assert headers["Sec-Fetch-Mode"] == "cors"
    assert "Sec-Fetch-User" not in headers
    assert "Upgrade-Insecure-Requests" not in headers


def test_next_page_is_requested_in_english(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    make_client(tmp_path).get_subscriptions()

    # The landing page and the next page of deliveries, like every further page, are requested in English
    for call in mock.calls[:2]:
        assert "lc-acbde=en_GB" in call.request.headers["Cookie"]
    assert DE_DELIVERIES_PAGINATE_URL.fullmatch(mock.calls[1].request.url or "")


def test_next_page_without_charset_is_utf8(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_subscriptions_next_page(mock)
    subscriptions = make_client(tmp_path).get_subscriptions()

    assert "charset" not in mock.calls[1].response.headers["Content-Type"]
    assert all(s.next_delivery_date for s in subscriptions[-2:])


def test_next_page_of_deliveries(
    tmp_path: Path, mock: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    landing = read_fixture("de/landing.html")
    # A further card like the second one of the landing page, a month later
    fragment = (
        str(BeautifulSoup(landing, "html.parser").select(selectors.DELIVERY_CARD)[1])
        .replace("Arriving Tue, 1 Dec", "Arriving Fri, 1 Jan")
        .replace("Last day to edit Thu, 26 Nov", "Last day to edit Sun, 27 Dec")
        .replace("1796079600000", "1798758000000")
    )
    mock.post(DE_DELIVERIES_PAGINATE_URL, body=f"<div>{fragment}</div>".encode(), content_type="text/html")
    register_de_pages(mock, landing=landing)

    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    # The delivery page of the further card is answered with the page of the first delivery.
    assert len(deliveries) == 3
    assert deliveries[2].url and "deliveryDate=1798758000000" in deliveries[2].url
    assert "The delivery card shows 2027-01-01, but its page shows 2026-11-01." in caplog.text
    request = next(c.request for c in mock.calls if DE_DELIVERIES_PAGINATE_URL.fullmatch(c.request.url or ""))
    next_url = json.loads(request.body or "")["nextUrl"]
    assert next_url.startswith("/api/marketplaces/A1PA6795UKMFR9/customer/replenishment/fulfillment/deliveries?")
    assert "&amp;" not in next_url


def test_empty_next_page_of_deliveries(tmp_path: Path, mock: responses.RequestsMock) -> None:
    # Amazon's answer if there are no further deliveries, as the fixture has it
    assert read_fixture("de/deliveries-page-2.html").strip() == "<div></div>"
    register_de_pages(mock)

    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    assert [d.date for d in deliveries] == [date(2026, 11, 1), date(2026, 12, 1)]


def test_next_page_of_deliveries_without_cards(tmp_path: Path, mock: responses.RequestsMock) -> None:
    mock.post(DE_DELIVERIES_PAGINATE_URL, body=b"<div>New</div>", content_type="text/html")
    register_de_pages(mock)

    with pytest.raises(PageStructureError, match="No delivery cards"):
        make_client(tmp_path).get_upcoming_deliveries()


def test_repeated_next_page_stops(tmp_path: Path, mock: responses.RequestsMock) -> None:
    landing = with_subscriptions_next_page(read_fixture("de/landing.html"))
    mock.get(DE_LANDING_URL, body=landing.encode(), content_type="text/html;charset=UTF-8")
    mock.post(DE_SUBSCRIPTIONS_PAGINATE_URL, body=landing.encode(), content_type="text/html")

    with pytest.raises(PageStructureError, match="repeat the next page"):
        make_client(tmp_path).get_subscriptions()


def test_debug_writes_next_pages(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_subscriptions_next_page(mock)
    make_client(tmp_path, debug=True).get_subscriptions()

    written = (tmp_path / "output" / "paginate-subscriptions_0.html").read_text(encoding="utf-8")
    assert written == subscriptions_page_2()
    written = (tmp_path / "output" / "paginate-deliveries_0.html").read_text(encoding="utf-8")
    assert written == read_fixture("de/deliveries-page-2.html")


def test_without_login_sends_no_request(tmp_path: Path, mock: responses.RequestsMock) -> None:
    with pytest.raises(SessionExpiredError, match="no stored Amazon session"):
        make_client(tmp_path, logged_in=False).get_subscriptions()
    assert len(mock.calls) == 0


def test_redirect_to_sign_in(tmp_path: Path, mock: responses.RequestsMock) -> None:
    sign_in = f"{DE_BASE_URL}/ap/signin"
    mock.get(DE_LANDING_URL, status=302, headers={"Location": f"{sign_in}?openid.return_to=x"})
    mock.get(sign_in, body="<html><body>Sign in</body></html>")

    with pytest.raises(SessionExpiredError, match="sign-in page"):
        make_client(tmp_path).get_subscriptions()


def test_sign_in_form(tmp_path: Path, mock: responses.RequestsMock) -> None:
    mock.get(DE_LANDING_URL, body='<form name="signIn"><input id="ap_email"></form>')

    with pytest.raises(SessionExpiredError, match="expired"):
        make_client(tmp_path).get_subscriptions()


def test_captcha(tmp_path: Path, mock: responses.RequestsMock) -> None:
    mock.get(DE_LANDING_URL, body='<form action="/errors/validateCaptcha"></form>')

    with pytest.raises(CaptchaError):
        make_client(tmp_path).get_subscriptions()


def test_server_error(tmp_path: Path, mock: responses.RequestsMock) -> None:
    mock.get(DE_LANDING_URL, status=503, body="")

    with pytest.raises(SubscriptionsError, match="returned 503"):
        make_client(tmp_path).get_subscriptions()


def test_changed_page(tmp_path: Path, mock: responses.RequestsMock) -> None:
    mock.get(DE_LANDING_URL, body="<html><body>Something new</body></html>")

    with pytest.raises(PageStructureError):
        make_client(tmp_path).get_subscriptions()


@pytest.mark.parametrize(
    "url",
    [
        f"{DE_BASE_URL}/auto-deliveries/ajax/bulkSkip/",
        f"{DE_BASE_URL}/auto-deliveries/ajax/subscriptions/edit/?subscriptionId=1&deliveryDate=1",
        f"{DE_BASE_URL}/auto-deliveries/checkout/subscribe?deliveryDate=1",
        f"{DE_BASE_URL}/auto-deliveries/?deliveryDate=1&action=ajax",
        f"{DE_BASE_URL}/auto-deliveries/?subscriptionId=1",
        f"{DE_BASE_URL}/acp/myd-hub-subscriptions-card-desktop/x/skip?a=1",
        f"{DE_BASE_URL}/acp/myd-hub-subscriptions-card-desktop/x/paginate/../skip?a=1",
        "https://www.amazon.com/auto-deliveries",
        "http://www.amazon.de/auto-deliveries",
        f"{DE_BASE_URL}/auto-deliveries#x",
        f"{DE_BASE_URL}/auto-deliveries/ajax/subscription/backupItem?subscriptionId=1&ASIN=B0TEST0001",
        f"{DE_BASE_URL}/auto-deliveries/ajax/subscription/?shipId=1",
        f"{DE_BASE_URL}/dp/B0TEST0001?smid=1",
        f"{DE_BASE_URL}/dp/B0TEST0001/ref=x",
        f"{DE_BASE_URL}/gp/product/B0TEST0001",
    ],
)
def test_refuses_unknown_urls(tmp_path: Path, url: str) -> None:
    with pytest.raises(SubscriptionsError, match="Refused"):
        make_client(tmp_path)._check_read_only(url)


@pytest.mark.parametrize(
    "url",
    [
        DE_LANDING_URL,
        f"{DE_LANDING_URL}/",
        f"{DE_LANDING_URL}/?_encoding=UTF8&shipId=X&deliveryDate=1793487600000&deliveryBundleId=abc&ref_=x",
        f"{DE_BASE_URL}/acp/myd-hub-deliveries-card-desktop/myd-hub-x-1/paginate?page-type=RCXSubs&stamp=1",
        f"{DE_BASE_URL}/auto-deliveries/ajax/subscription/?subscriptionId=SNST0_1&subAsin=B0TEST0001",
        f"{DE_BASE_URL}/dp/B0TEST0001",
    ],
)
def test_allows_read_only_urls(tmp_path: Path, url: str) -> None:
    make_client(tmp_path)._check_read_only(url)


def test_refuses_unknown_next_url(tmp_path: Path, mock: responses.RequestsMock) -> None:
    landing = with_subscriptions_next_page(read_fixture("de/landing.html")).replace(
        "/replenishment/subscriptions?paginationContext", "/replenishment/subscriptions/skip?paginationContext"
    )
    mock.get(DE_LANDING_URL, body=landing.encode(), content_type="text/html;charset=UTF-8")

    with pytest.raises(SubscriptionsError, match="Refused to load the next page"):
        make_client(tmp_path).get_subscriptions()
    assert [c.request.method for c in mock.calls] == ["GET"]


def test_unsupported_domain(tmp_path: Path) -> None:
    # amazon.com.br offers no English pages
    with pytest.raises(SubscriptionsError, match="English"):
        make_client(tmp_path, domain="amazon.com.br")


def test_refuses_another_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = make_session(tmp_path)
    monkeypatch.setitem(session.config.constants.REQUEST_COOKIES, "lc-acbde", "de_DE")

    with pytest.raises(SubscriptionsError, match="another language than English"):
        SubscriptionsClient(session, today=DE_TODAY)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("/-/en/dp/B0TEST0001", f"{DE_BASE_URL}/dp/B0TEST0001"),
        ("/-/en_GB/auto-deliveries/?deliveryDate=1", f"{DE_BASE_URL}/auto-deliveries/?deliveryDate=1"),
        (f"{DE_BASE_URL}/-/en/dp/B0TEST0001", f"{DE_BASE_URL}/dp/B0TEST0001"),
        ("/dp/B0TEST0001", f"{DE_BASE_URL}/dp/B0TEST0001"),
        # Only a language prefix at the start of the path
        ("/dp/B0TEST0001/-/en/x", f"{DE_BASE_URL}/dp/B0TEST0001/-/en/x"),
    ],
)
def test_absolute_drops_the_language_prefix(tmp_path: Path, url: str, expected: str) -> None:
    # The English pages link with a language prefix, which the allow-list does not know
    assert make_client(tmp_path)._absolute(url) == expected
