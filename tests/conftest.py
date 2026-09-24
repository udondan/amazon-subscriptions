import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from amazonorders.conf import AmazonOrdersConfig
from amazonorders.session import AmazonSession
from requests import PreparedRequest

from amazon_subscriptions.locales import get_locale
from amazon_subscriptions.locales.base import SubscriptionLocale

FIXTURES = Path(__file__).parent / "fixtures"
#: The day the amazon.de fixtures were captured.
DE_TODAY = date(2026, 9, 24)

DE_BASE_URL = "https://www.amazon.de"
DE_LANDING_URL = f"{DE_BASE_URL}/auto-deliveries"
#: ``deliveryDate`` of the second delivery card of the landing fixture
DE_DELIVERY_2_EPOCH = "1793487600000"
DE_SUBSCRIPTIONS_PAGINATE_URL = re.compile(
    re.escape(DE_BASE_URL) + r"/acp/myd-hub-subscriptions-card-desktop/[^/]+/paginate\?.*"
)
DE_DETAIL_URL = re.compile(re.escape(DE_BASE_URL) + r"/auto-deliveries/ajax/subscription/\?.*")
DE_PRODUCT_URL = re.compile(re.escape(DE_BASE_URL) + r"/dp/[A-Z0-9]{10}")
#: The product page fixtures by ASIN; all other ASINs get ``de/product.html``.
DE_PRODUCT_PAGES = {"B0TEST0024": "product-list-price", "B0TEST0025": "product-unavailable"}
DE_DELIVERIES_PAGINATE_URL = re.compile(
    re.escape(DE_BASE_URL) + r"/acp/myd-hub-deliveries-card-desktop/[^/]+/paginate\?.*"
)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def de() -> SubscriptionLocale:
    return get_locale("amazon.de")


def without_deliveries_next_page(html: str) -> str:
    """The landing fixture without its next page of deliveries, which has no fixture yet."""
    return re.sub(r'data-next-url="[^"]*/fulfillment/deliveries[^"]*"', "", html)


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
    landing = landing if landing is not None else without_deliveries_next_page(read_fixture("de/landing.html"))
    mock.get(DE_LANDING_URL, body=landing.encode(), content_type="text/html;charset=UTF-8")
    mock.post(
        DE_SUBSCRIPTIONS_PAGINATE_URL,
        body=read_fixture("de/subscriptions-page-2.html").encode(),
        content_type="text/html",
    )
    mock.add_callback(responses.GET, re.compile(re.escape(DE_BASE_URL) + r"/auto-deliveries/\?.*"), _delivery_page)
    mock.get(DE_DETAIL_URL, body=read_fixture("de/subscription-detail.html").encode(), content_type="text/html")
