from amazon_subscriptions.parse import BackupItem, parse_subscription_detail
from tests.conftest import read_fixture


def test_backup_item() -> None:
    backup = parse_subscription_detail(read_fixture("de/subscription-detail.html"))
    assert backup == BackupItem(
        asin="B0TEST0056",
        title="Testartikel 50 incididunt ut labore et dolore magna aliqua enim minim veniam quis nostrud exercitation "
        "ullamco laboris nisi",
    )


def test_without_backup_item() -> None:
    assert parse_subscription_detail('<html><body><div class="productInformation"></div></body></html>') is None
