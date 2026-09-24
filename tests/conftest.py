from datetime import date
from pathlib import Path

import pytest

from amazon_subscriptions.locales import get_locale
from amazon_subscriptions.locales.base import SubscriptionLocale

FIXTURES = Path(__file__).parent / "fixtures"
#: The day the amazon.de fixtures were captured.
DE_TODAY = date(2026, 9, 24)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def de() -> SubscriptionLocale:
    return get_locale("amazon.de")
