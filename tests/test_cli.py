import json
from collections.abc import Iterator
from datetime import date
from functools import partial
from pathlib import Path

import amazonorders.cli
import amazonorders.conf
import pytest
import responses
from amazonorders.conf import AmazonOrdersConfig
from click.testing import CliRunner

from amazon_subscriptions import cli as cli_module
from amazon_subscriptions.cli import cli
from amazon_subscriptions.client import SubscriptionsClient
from tests.conftest import (
    DE_BASE_URL,
    DE_LANDING_URL,
    DE_TODAY,
    register_broken_delivery_1,
    register_de_pages,
    register_de_product_pages,
    store_login_cookies,
)


@pytest.fixture(autouse=True)
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the config and cookies of amazon-orders below ``tmp_path``."""
    monkeypatch.setattr(amazonorders.conf, "DEFAULT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cli_module, "SubscriptionsClient", partial(SubscriptionsClient, today=DE_TODAY))
    return tmp_path


@pytest.fixture
def mock() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


def log_in(domain: str) -> None:
    store_login_cookies(AmazonOrdersConfig(data={"domain": domain}))


@pytest.mark.parametrize("name", ["login", "logout", "check-session"])
def test_session_commands_are_those_of_amazon_orders(name: str) -> None:
    assert cli.commands[name] is amazonorders.cli.amazon_orders_cli.commands[name]


def test_check_session_with_session() -> None:
    log_in("amazon.de")
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "check-session"])
    assert result.exit_code == 0, result.output
    assert "A persisted session exists" in result.output


def test_check_session() -> None:
    result = CliRunner().invoke(cli, ["check-session"])
    assert result.exit_code == 0, result.output
    assert "No persisted session exists" in result.output


def test_logout(config_dir: Path, mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    mock.get(f"{DE_BASE_URL}/gp/flex/sign-out.html")
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "logout"])
    assert result.exit_code == 0, result.output
    assert json.loads((config_dir / "cookies.amazon.de.json").read_text()) == []


def test_uses_a_session_of_the_cookie_jar_shared_by_all_sites(config_dir: Path) -> None:
    """amazon-orders kept the sessions of all sites in one jar before each site had its own."""
    cookies = dict.fromkeys(AmazonOrdersConfig(data={"domain": "amazon.de"}).constants.COOKIES_SET_WHEN_AUTHENTICATED)
    jar = [{"name": name, "value": "test", "domain": ".amazon.de"} for name in cookies]
    (config_dir / "cookies.json").write_text(json.dumps(jar), encoding="utf-8")
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "check-session"])
    assert result.exit_code == 0, result.output
    assert "A persisted session exists" in result.output


@pytest.mark.parametrize(
    ("args", "hint"),
    [
        ([], "amazon-subscriptions login"),
        (["--domain", "amazon.de"], "amazon-subscriptions --domain amazon.de login"),
    ],
)
def test_expired_session_shows_how_to_log_in(
    args: list[str], hint: str, config_dir: Path, mock: responses.RequestsMock
) -> None:
    # Without --domain, the domain configured for amazon-orders is used
    (config_dir / "config.yml").write_text("domain: amazon.de\n")
    result = CliRunner().invoke(cli, [*args, "list"])
    assert result.exit_code == 1
    assert hint in result.output
    assert hint.replace(" login", " logout") in result.output
    assert len(mock.calls) == 0


def test_list_json(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "list", "--json"])
    assert result.exit_code == 0, result.output

    subscriptions = json.loads(result.output)
    assert len(subscriptions) == 30
    assert all(date.fromisoformat(s["next_delivery_date"]) >= DE_TODAY for s in subscriptions)
    assert any(isinstance(s["subscription_price"], str) for s in subscriptions)


def test_list_text(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "list"])
    assert result.exit_code == 0, result.output
    assert result.output.rstrip().endswith("30 subscriptions")
    assert "2026-11-01  " in result.output


def test_list_with_prices(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    register_de_product_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "list", "--with-prices"])
    assert result.exit_code == 0, result.output
    assert "(regular 8.69 EUR, 57.93 EUR/l, rrp 11.99 EUR)" in result.output
    assert "(regular 6.13 EUR, 52.62 EUR/kg, was 6.45 EUR)" in result.output
    assert "(regular 56.48 EUR, 9.41 EUR/count)" in result.output

    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "list", "--json", "--with-prices"])
    assert result.exit_code == 0, result.output
    by_asin = {s["asin"]: s for s in json.loads(result.output)}
    assert (by_asin["B0TEST0024"]["price"], by_asin["B0TEST0024"]["list_price"]) == ("8.69", "11.99")
    assert (by_asin["B0TEST0024"]["unit_price"], by_asin["B0TEST0024"]["unit_price_unit"]) == ("57.93", "l")
    assert (by_asin["B0TEST0024"]["list_price_type"], by_asin["B0TEST0024"]["list_price_source"]) == ("rrp", "buybox")
    assert by_asin["B0TEST0042"]["list_price_type"] == "was"
    assert all(s["alternative_offer"] is None for s in by_asin.values())


def test_upcoming(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "upcoming"])
    assert result.exit_code == 0, result.output
    assert "2026-11-01: 11 items, total -, changes until 2026-10-27" in result.output
    assert "2026-12-01: 17 items, total - EUR" not in result.output
    assert "2026-12-01: 17 items, total -, changes until 2026-11-26" in result.output
    assert "12.74 EUR (-15%)" in result.output


def test_upcoming_json(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "upcoming", "--json"])
    assert result.exit_code == 0, result.output
    deliveries = json.loads(result.output)
    assert [(d["date"], d["total"], d["currency"]) for d in deliveries] == [
        ("2026-11-01", None, "EUR"),
        ("2026-12-01", None, "EUR"),
    ]
    [second] = [item for item in deliveries[0]["items"] if item["title"].startswith("Product 02 ")]
    assert (second["price"], second["discount_percent"], second["substitute"]) == ("12.74", 15, False)


@pytest.mark.parametrize(
    "args", [["list", "--json", "--with-prices"], ["list", "--json"], ["upcoming", "--json"], ["upcoming"]]
)
def test_delivery_page_without_date_is_a_partial_result(
    mock: responses.RequestsMock, failed_dir: Path, args: list[str]
) -> None:
    log_in("amazon.de")
    register_broken_delivery_1(mock)
    register_de_pages(mock)
    register_de_product_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", *args])

    assert result.exit_code == 2, result.output
    [saved] = [p for p in failed_dir.iterdir() if p.name.endswith("_2.html")]
    assert result.stderr.startswith("Error: No delivery date found, it was taken from the URL (page: https://")
    assert f", page saved to {saved}\n" in result.stderr
    if "--json" not in args:
        assert "2026-11-01: 11 items, total -, changes until 2026-10-27  [incomplete]" in result.stdout
        return
    objects = json.loads(result.stdout)
    [error] = {json.dumps(e) for o in objects for e in o["parse_errors"]}
    url = json.loads(error)["url"]
    assert url.startswith(f"{DE_LANDING_URL}/?") and "deliveryDate=1793487600000" in url
    assert json.loads(error) == {
        "url": url,
        "message": "No delivery date found, it was taken from the URL",
        "selector": "[data-testid='ddp-atd-delivery-date']",
        "html_path": str(saved),
    }
    if args[0] == "upcoming":
        assert [(d["date"], len(d["items"])) for d in objects] == [("2026-11-01", 11), ("2026-12-01", 17)]


def test_complete_result_has_no_errors(mock: responses.RequestsMock, failed_dir: Path) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "upcoming", "--json"])
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert all(d["parse_errors"] == [] for d in json.loads(result.stdout))
    assert not failed_dir.exists()


def test_changed_page_is_an_error(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    mock.get(DE_LANDING_URL, body="<html><body>Something new</body></html>")
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "list", "--json"])
    assert result.exit_code == 1
    assert "Error: No subscriptions found" in result.output


def test_reads_the_pages_in_english_with_a_language_package(config_dir: Path, mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    # A language package of amazon-orders would request the pages in another language
    (config_dir / "config.yml").write_text("domain: amazon.de\nlanguage_package: amazon_orders_de\n")
    register_de_pages(mock)
    result = CliRunner().invoke(cli, ["list", "--json"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == 30
    assert "lc-acbde=en_GB" in mock.calls[0].request.headers["Cookie"]
    # The configuration file is not changed
    assert "language_package: amazon_orders_de" in (config_dir / "config.yml").read_text()
