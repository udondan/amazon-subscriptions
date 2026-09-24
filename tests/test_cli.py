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


def test_login_uses_the_session(config_dir: Path) -> None:
    log_in("amazon.de")
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "login"])
    assert result.exit_code == 0, result.output
    assert "A persisted session exists" in result.output


def test_check_session() -> None:
    result = CliRunner().invoke(cli, ["check-session"])
    assert result.exit_code == 0, result.output
    assert "No persisted session exists" in result.output


def test_logout(config_dir: Path) -> None:
    log_in("amazon.de")
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "logout"])
    assert result.exit_code == 0, result.output
    assert json.loads((config_dir / "cookies.json").read_text()) == {}


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
    assert len(subscriptions) == 32
    assert all(date.fromisoformat(s["next_delivery_date"]) >= DE_TODAY for s in subscriptions)
    assert any(isinstance(s["subscription_price"], str) for s in subscriptions)


def test_list_text(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "list"])
    assert result.exit_code == 0, result.output
    assert result.output.rstrip().endswith("32 subscriptions")
    assert "2026-10-01  " in result.output


def test_list_with_prices(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    register_de_product_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "list", "--with-prices"])
    assert result.exit_code == 0, result.output
    assert "(regular 17.49 EUR, 24.99 EUR/l, uvp 27.99 EUR)" in result.output
    assert "(regular 5.98 EUR, 1.50 EUR/Stück, uvp 5.75 EUR, alternative offer 5.45 EUR from Testhändler 02)" in (
        result.output
    )

    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "list", "--json", "--with-prices"])
    assert result.exit_code == 0, result.output
    by_asin = {s["asin"]: s for s in json.loads(result.output)}
    assert (by_asin["B0TEST0024"]["price"], by_asin["B0TEST0024"]["list_price"]) == ("17.49", "27.99")
    assert (by_asin["B0TEST0024"]["unit_price"], by_asin["B0TEST0024"]["unit_price_unit"]) == ("24.99", "l")
    assert (by_asin["B0TEST0024"]["list_price_type"], by_asin["B0TEST0024"]["list_price_source"]) == ("uvp", "buybox")
    assert by_asin["B0TEST0027"]["alternative_offer"] == {
        "price": "5.45",
        "unit_price": "1.36",
        "unit_price_unit": "Stück",
        "seller": "Testhändler 02",
        "seller_id": None,
        "subscribable": False,
    }


def test_upcoming(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "upcoming"])
    assert result.exit_code == 0, result.output
    assert "2026-10-01: 11 items, total 150.19 EUR, changes until 2026-09-26" in result.output
    assert "2026-11-01: 16 items, total - EUR" not in result.output
    assert "2026-11-01: 16 items, total -" in result.output
    assert "  [backup product B0TEST0056]" in result.output


def test_upcoming_json(mock: responses.RequestsMock) -> None:
    log_in("amazon.de")
    register_de_pages(mock)
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "upcoming", "--json"])
    assert result.exit_code == 0, result.output
    deliveries = json.loads(result.output)
    assert [(d["date"], d["total"], d["currency"]) for d in deliveries] == [
        ("2026-10-01", "150.19", "EUR"),
        ("2026-11-01", None, "EUR"),
    ]
    [substitute] = [item for d in deliveries for item in d["items"] if item["substitute"]]
    assert (substitute["asin"], substitute["substitute_asin"]) == ("B0TEST0024", "B0TEST0056")


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
        assert "2026-10-01: 11 items, total 150.19 EUR, changes until 2026-09-26  [incomplete]" in result.stdout
        return
    objects = json.loads(result.stdout)
    [error] = {json.dumps(e) for o in objects for e in o["parse_errors"]}
    url = json.loads(error)["url"]
    assert url.startswith(f"{DE_LANDING_URL}/?") and "deliveryDate=1790805600000" in url
    assert json.loads(error) == {
        "url": url,
        "message": "No delivery date found, it was taken from the URL",
        "selector": "[data-testid='ddp-atd-delivery-date']",
        "html_path": str(saved),
    }
    if args[0] == "upcoming":
        assert [(d["date"], len(d["items"])) for d in objects] == [("2026-10-01", 11), ("2026-11-01", 16)]


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
    mock.get(DE_LANDING_URL, body="<html><body>Etwas Neues</body></html>")
    result = CliRunner().invoke(cli, ["--domain", "amazon.de", "list", "--json"])
    assert result.exit_code == 1
    assert "Error: No subscriptions found" in result.output
