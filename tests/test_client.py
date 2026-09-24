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
from amazon_subscriptions.parse import parse_acp_widget, selectors
from tests.conftest import (
    DE_BASE_URL,
    DE_DELIVERIES_PAGINATE_URL,
    DE_DETAIL_URL,
    DE_LANDING_URL,
    DE_SUBSCRIPTIONS_PAGINATE_URL,
    DE_TODAY,
    make_session,
    read_fixture,
    register_de_pages,
    without_deliveries_next_page,
)


@pytest.fixture
def mock() -> responses.RequestsMock:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


def make_client(tmp_path: Path, **kwargs: object) -> SubscriptionsClient:
    return SubscriptionsClient(make_session(tmp_path, **kwargs), today=DE_TODAY)


def test_loads_subscriptions_and_deliveries(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    client = make_client(tmp_path)

    subscriptions = client.get_subscriptions()
    deliveries = client.get_upcoming_deliveries()

    assert len(subscriptions) == 32
    assert len({s.subscription_id for s in subscriptions}) == 32
    assert all(s.next_delivery_date for s in subscriptions)
    assert all(s.product_url and s.product_url.startswith(f"{DE_BASE_URL}/dp/B0TEST") for s in subscriptions)

    assert [(d.date, len(d.items), d.total) for d in deliveries] == [
        (date(2026, 10, 1), 11, Decimal("150.19")),
        (date(2026, 11, 1), 16, None),
    ]
    for delivery in deliveries:
        assert delivery.url and delivery.url.startswith(f"{DE_LANDING_URL}/?")
        assert delivery.delivery_bundle_id
        assert all(item.subscription_id for item in delivery.items)
    assert any(s.subscription_price is not None for s in subscriptions)

    # Both results come from one load of the pages
    assert [(c.request.method, urlparse(c.request.url).path) for c in mock.calls] == [
        ("GET", "/auto-deliveries"),
        ("POST", urlparse(mock.calls[1].request.url).path),
        ("GET", "/auto-deliveries/"),
        ("GET", "/auto-deliveries/"),
        # Detail sheet of the subscription whose backup product is sent
        ("GET", "/auto-deliveries/ajax/subscription/"),
    ]


def test_substitute_asin(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    [substitute] = [item for d in deliveries for item in d.items if item.substitute]
    assert substitute.asin == "B0TEST0024"
    assert substitute.substitute_asin == "B0TEST0056"
    assert all(item.substitute_asin is None for d in deliveries for item in d.items if not item.substitute)
    [request] = [c.request for c in mock.calls if DE_DETAIL_URL.fullmatch(c.request.url or "")]
    assert parse_qs(urlparse(request.url).query) == {
        "subscriptionId": ["SNST0_0B3FB3F12A77505F46C3"],
        "subAsin": ["B0TEST0024"],
        "enableMydExperience": ["1"],
        "clientName": ["mydHub"],
    }


def test_substitute_with_other_backup_product(
    tmp_path: Path, mock: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    detail = read_fixture("de/subscription-detail.html").replace(
        "Testartikel 50 incididunt ut labore", "Testartikel 51 ipsum dolor sit"
    )
    mock.get(DE_DETAIL_URL, body=detail.encode(), content_type="text/html")
    register_de_pages(mock)

    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    assert all(item.substitute_asin is None for d in deliveries for item in d.items)
    assert "is not the item 'Testartikel 50" in caplog.text


def test_substitute_detail_sheet_error(
    tmp_path: Path, mock: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock.get(DE_DETAIL_URL, status=500, body="")
    register_de_pages(mock)

    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    assert all(item.substitute_asin is None for d in deliveries for item in d.items)
    assert "was not loaded" in caplog.text


def test_substitute_detail_sheet_captcha(tmp_path: Path, mock: responses.RequestsMock) -> None:
    mock.get(DE_DETAIL_URL, body='<form action="/errors/validateCaptcha"></form>')
    register_de_pages(mock)

    with pytest.raises(CaptchaError):
        make_client(tmp_path).get_upcoming_deliveries()


def test_next_page_is_requested_like_the_browser(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    make_client(tmp_path).get_subscriptions()

    landing = read_fixture("de/landing.html")
    widget = parse_acp_widget(landing, selectors.SUBSCRIPTIONS_NEXT_PAGE)
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
    assert json.loads(request.body or "") == {
        "nextUrl": "/api/marketplaces/A1PA6795UKMFR9/customer/replenishment/subscriptions"
        "?paginationContext.next=30&paginationContext.pageSize=30"
    }
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


def test_next_page_without_charset_is_utf8(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    subscriptions = make_client(tmp_path).get_subscriptions()

    assert "charset" not in mock.calls[1].response.headers["Content-Type"]
    # The dates of the second page follow "Nächste Lieferung:", which only matches if decoded as UTF-8
    assert all(s.next_delivery_date for s in subscriptions[-2:])


def test_next_page_of_deliveries(
    tmp_path: Path, mock: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    landing = read_fixture("de/landing.html")
    # A further card like the second one of the landing page, a month later
    fragment = (
        str(BeautifulSoup(landing, "html.parser").select(selectors.DELIVERY_CARD)[1])
        .replace("1. Nov.", "1. Dez.")
        .replace("27. Okt.", "26. Nov.")
        .replace("1793487600000", "1796079600000")
    )
    register_de_pages(mock, landing=landing)
    mock.post(DE_DELIVERIES_PAGINATE_URL, body=f"<div>{fragment}</div>".encode(), content_type="text/html")

    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    # The delivery page of the further card is answered with the page of the first delivery.
    assert len(deliveries) == 3
    assert deliveries[2].url and "deliveryDate=1796079600000" in deliveries[2].url
    assert "The delivery card shows 2026-12-01, but its page shows 2026-10-01." in caplog.text
    request = next(c.request for c in mock.calls if DE_DELIVERIES_PAGINATE_URL.fullmatch(c.request.url or ""))
    next_url = json.loads(request.body or "")["nextUrl"]
    assert next_url.startswith("/api/marketplaces/A1PA6795UKMFR9/customer/replenishment/fulfillment/deliveries?")
    assert "&amp;" not in next_url


def test_empty_next_page_of_deliveries(tmp_path: Path, mock: responses.RequestsMock) -> None:
    # Amazon's answer if there are no further deliveries
    register_de_pages(mock, landing=read_fixture("de/landing.html"))
    mock.post(DE_DELIVERIES_PAGINATE_URL, body=b"<div></div>", content_type="text/html")

    deliveries = make_client(tmp_path).get_upcoming_deliveries()

    assert [d.date for d in deliveries] == [date(2026, 10, 1), date(2026, 11, 1)]


def test_next_page_of_deliveries_without_cards(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock, landing=read_fixture("de/landing.html"))
    mock.post(DE_DELIVERIES_PAGINATE_URL, body=b"<div>Neu</div>", content_type="text/html")

    with pytest.raises(PageStructureError, match="No delivery cards"):
        make_client(tmp_path).get_upcoming_deliveries()


def test_repeated_next_page_stops(tmp_path: Path, mock: responses.RequestsMock) -> None:
    landing = without_deliveries_next_page(read_fixture("de/landing.html"))
    mock.get(DE_LANDING_URL, body=landing.encode(), content_type="text/html;charset=UTF-8")
    mock.post(DE_SUBSCRIPTIONS_PAGINATE_URL, body=landing.encode(), content_type="text/html")

    with pytest.raises(PageStructureError, match="repeat the next page"):
        make_client(tmp_path).get_subscriptions()


def test_debug_writes_next_pages(tmp_path: Path, mock: responses.RequestsMock) -> None:
    register_de_pages(mock)
    make_client(tmp_path, debug=True).get_subscriptions()

    written = (tmp_path / "output" / "paginate-subscriptions_0.html").read_text(encoding="utf-8")
    assert written == read_fixture("de/subscriptions-page-2.html")


def test_without_login_sends_no_request(tmp_path: Path, mock: responses.RequestsMock) -> None:
    with pytest.raises(SessionExpiredError, match="no stored Amazon session"):
        make_client(tmp_path, logged_in=False).get_subscriptions()
    assert len(mock.calls) == 0


def test_redirect_to_sign_in(tmp_path: Path, mock: responses.RequestsMock) -> None:
    sign_in = f"{DE_BASE_URL}/ap/signin"
    mock.get(DE_LANDING_URL, status=302, headers={"Location": f"{sign_in}?openid.return_to=x"})
    mock.get(sign_in, body="<html><body>Anmelden</body></html>")

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
    mock.get(DE_LANDING_URL, body="<html><body>Etwas Neues</body></html>")

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
    ],
)
def test_allows_read_only_urls(tmp_path: Path, url: str) -> None:
    make_client(tmp_path)._check_read_only(url)


def test_refuses_unknown_next_url(tmp_path: Path, mock: responses.RequestsMock) -> None:
    landing = read_fixture("de/landing.html").replace(
        "/replenishment/subscriptions?paginationContext", "/replenishment/subscriptions/skip?paginationContext"
    )
    mock.get(DE_LANDING_URL, body=landing.encode(), content_type="text/html;charset=UTF-8")

    with pytest.raises(SubscriptionsError, match="Refused to load the next page"):
        make_client(tmp_path).get_subscriptions()
    assert [c.request.method for c in mock.calls] == ["GET"]


def test_unsupported_domain(tmp_path: Path) -> None:
    with pytest.raises(SubscriptionsError):
        make_client(tmp_path, domain="amazon.co.jp")
