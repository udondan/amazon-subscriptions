import json
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from amazonorders.conf import AmazonOrdersConfig
from amazonorders.session import AmazonSession
from bs4 import BeautifulSoup
from requests import PreparedRequest

from amazon_subscriptions.locales import get_locale
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.parse import selectors

FIXTURES = Path(__file__).parent / "fixtures"
#: The day the amazon.de fixtures were captured.
DE_TODAY = date(2026, 10, 21)

DE_BASE_URL = "https://www.amazon.de"
DE_LANDING_URL = f"{DE_BASE_URL}/auto-deliveries"
#: ``deliveryDate`` of the first delivery card of the landing fixture, 1 November 2026 in Europe/Berlin
DE_DELIVERY_1_EPOCH = "1793487600000"
#: ``deliveryDate`` of the second delivery card of the landing fixture, 1 December 2026
DE_DELIVERY_2_EPOCH = "1796079600000"
#: The delivery page of the first delivery card
DE_DELIVERY_1_URL = re.compile(
    re.escape(DE_BASE_URL) + r"/auto-deliveries/\?.*\bdeliveryDate=" + DE_DELIVERY_1_EPOCH + r"\b.*"
)
DE_SUBSCRIPTIONS_PAGINATE_URL = re.compile(
    re.escape(DE_BASE_URL) + r"/acp/myd-hub-subscriptions-card-desktop/[^/]+/paginate\?.*"
)
DE_DETAIL_URL = re.compile(re.escape(DE_BASE_URL) + r"/auto-deliveries/ajax/subscription/\?.*")
DE_PRODUCT_URL = re.compile(re.escape(DE_BASE_URL) + r"/dp/[A-Z0-9]{10}")
#: The product page fixtures by ASIN; all other ASINs get ``de/product.html``, the page of B0TEST0026.
DE_PRODUCT_PAGES = {
    "B0TEST0024": "product-rrp",
    "B0TEST0042": "product-was",
    "B0TEST0044": "product-unavailable",
    "B0TEST0045": "product-single-offer",
    "B0TEST0049": "product-no-buybox",
}
DE_DELIVERIES_PAGINATE_URL = re.compile(
    re.escape(DE_BASE_URL) + r"/acp/myd-hub-deliveries-card-desktop/[^/]+/paginate\?.*"
)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def de() -> SubscriptionLocale:
    return get_locale("amazon.de")


@pytest.fixture(autouse=True)
def failed_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Save the pages that could not be read below ``tmp_path`` and retry them without waiting."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("amazon_subscriptions.client.time.sleep", lambda seconds: None)
    return tmp_path / "cache" / "amazon-subscriptions" / "failed"


#: The next page of subscriptions as the landing page links it if there are more than 30 subscriptions
DE_SUBSCRIPTIONS_NEXT_URL = (
    "/api/marketplaces/A1PA6795UKMFR9/customer/replenishment/subscriptions"
    "?paginationContext.next=30&paginationContext.pageSize=30"
)
#: The alert of the first item of ``de/delivery-1.html``, which the substitute tests replace
DE_ITEM_ALERT = "Temporarily Unavailable"
#: The alert of a backup product, as amazon.de shows it
DE_SUBSTITUTE_ALERT = "Backup product will be shipped"


def with_subscriptions_next_page(landing: str) -> str:
    """The landing page with a link to a next page of subscriptions, which the captured account did not need."""
    soup = BeautifulSoup(landing, "html.parser")
    grid = soup.select_one(selectors.SUBSCRIPTIONS_GRID)
    assert grid is not None
    grid.append(soup.new_tag("div", attrs={"id": "endOfGridDesktop", "data-next-url": DE_SUBSCRIPTIONS_NEXT_URL}))
    return str(soup)


def subscriptions_page_2() -> str:
    """A next page of subscriptions: the first two tiles of the landing page as further subscriptions."""
    tiles = BeautifulSoup(read_fixture("de/landing.html"), "html.parser").select(selectors.SUBSCRIPTION_TILE)[:2]
    fragment = ""
    for number, tile in enumerate(tiles, 91):
        query = parse_qs(urlparse(str(tile["data-edit-url"])).query)
        fragment += (
            str(tile)
            .replace(query["subscriptionId"][0], f"SNST0_TESTPAGE2{number:010d}")
            .replace(query["subAsin"][0], f"B0TEST00{number}")
            .replace(f"Product {number - 90:02d}", f"Product {number}")
        )
    return f"<div>{fragment}</div>"


def register_subscriptions_next_page(mock: responses.RequestsMock) -> None:
    """Answer the requests of the client with the amazon.de fixtures and a next page of subscriptions."""
    mock.post(DE_SUBSCRIPTIONS_PAGINATE_URL, body=subscriptions_page_2().encode(), content_type="text/html")
    register_de_pages(mock, landing=with_subscriptions_next_page(read_fixture("de/landing.html")))


def substitute_item_title() -> str:
    """The title of the first item of ``de/delivery-1.html``, which the substitute tests take as a backup product."""
    soup = BeautifulSoup(read_fixture("de/delivery-1.html"), "html.parser")
    title = soup.select_one(f"{selectors.DELIVERY_ITEM} {selectors.DELIVERY_ITEM_TITLE}")
    assert title is not None
    return title.get_text(strip=True)


def delivery_1_with_backup_product() -> str:
    """The first delivery page with the alert of a backup product at its first item."""
    page = read_fixture("de/delivery-1.html")
    assert page.count(DE_ITEM_ALERT) == 1
    return page.replace(DE_ITEM_ALERT, DE_SUBSTITUTE_ALERT)


def register_delivery_1_with_backup_product(mock: responses.RequestsMock) -> None:
    """Answer the first request of the first delivery page with :func:`delivery_1_with_backup_product`.

    Must be called before :func:`register_de_pages`, whose page is sent afterwards.
    """
    body = delivery_1_with_backup_product().encode()
    mock.get(DE_DELIVERY_1_URL, body=body, content_type="text/html;charset=UTF-8")


@pytest.fixture
def substitute(mock: responses.RequestsMock) -> None:
    """The first item of the first delivery is a backup product, which the detail sheet names."""
    register_delivery_1_with_backup_product(mock)
    detail = read_fixture("de/subscription-detail.html")
    backup = BeautifulSoup(detail, "html.parser").select_one(
        f"{selectors.SUBSCRIPTION_DETAIL_BACKUP_LINK} {selectors.SUBSCRIPTION_DETAIL_BACKUP_TITLE}"
    )
    assert backup is not None
    detail = detail.replace(backup.get_text(strip=True), substitute_item_title())
    mock.get(DE_DETAIL_URL, body=detail.encode(), content_type="text/html")


@pytest.fixture
def mock() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


def delivery_1_without_date() -> str:
    """The first delivery page without its delivery date, as Amazon once served it."""
    soup = BeautifulSoup(read_fixture("de/delivery-1.html"), "html.parser")
    for tag in soup.select(selectors.DELIVERY_DATE):
        tag.decompose()
    return str(soup)


def register_broken_delivery_1(mock: responses.RequestsMock, times: int = 2) -> None:
    """Answer the first ``times`` requests of the first delivery page with the page without delivery date.

    Must be called before :func:`register_de_pages`, whose page is sent afterwards.
    """
    for _ in range(times):
        mock.get(DE_DELIVERY_1_URL, body=delivery_1_without_date().encode(), content_type="text/html;charset=UTF-8")


def make_session(tmp_path: Path, domain: str = "amazon.de", logged_in: bool = True, debug: bool = False) -> Any:
    """A session of amazon-orders that only uses files below ``tmp_path``."""
    config = AmazonOrdersConfig(
        config_path=str(tmp_path / "config.yml"),
        data={
            "domain": domain,
            "cookie_jar_path": str(tmp_path / "cookies.json"),
            "output_dir": str(tmp_path / "output"),
        },
    )
    if logged_in:
        store_login_cookies(config)
    return AmazonSession(config=config, debug=debug)


def store_login_cookies(config: Any) -> None:
    cookies = dict.fromkeys(config.constants.COOKIES_SET_WHEN_AUTHENTICATED, "test")
    Path(config.cookie_jar_path).parent.mkdir(parents=True, exist_ok=True)
    Path(config.cookie_jar_path).write_text(json.dumps(cookies), encoding="utf-8")


def _delivery_page(request: PreparedRequest) -> tuple[int, dict[str, str], bytes]:
    epoch = parse_qs(urlparse(request.url or "").query)["deliveryDate"][0]
    name = "delivery-2" if epoch == DE_DELIVERY_2_EPOCH else "delivery-1"
    return 200, {"Content-Type": "text/html;charset=UTF-8"}, read_fixture(f"de/{name}.html").encode()


def _product_page(request: PreparedRequest) -> tuple[int, dict[str, str], bytes]:
    asin = urlparse(request.url or "").path.rsplit("/", 1)[-1]
    name = DE_PRODUCT_PAGES.get(asin, "product")
    return 200, {"Content-Type": "text/html;charset=UTF-8"}, read_fixture(f"de/{name}.html").encode()


def register_de_product_pages(mock: responses.RequestsMock) -> None:
    """Answer the requests of product pages with the amazon.de product fixtures."""
    mock.add_callback(responses.GET, DE_PRODUCT_URL, _product_page)


def register_de_pages(mock: responses.RequestsMock, landing: str | None = None) -> None:
    """Answer the requests of the client with the amazon.de fixtures.

    The pages of the grid are sent without charset, as Amazon does.
    """
    landing = landing if landing is not None else read_fixture("de/landing.html")
    mock.get(DE_LANDING_URL, body=landing.encode(), content_type="text/html;charset=UTF-8")
    # All subscriptions fit on the landing page, there are only more deliveries
    mock.post(
        DE_DELIVERIES_PAGINATE_URL,
        body=read_fixture("de/deliveries-page-2.html").encode(),
        content_type="text/html",
    )
    mock.add_callback(responses.GET, re.compile(re.escape(DE_BASE_URL) + r"/auto-deliveries/\?.*"), _delivery_page)
    mock.get(DE_DETAIL_URL, body=read_fixture("de/subscription-detail.html").encode(), content_type="text/html")
