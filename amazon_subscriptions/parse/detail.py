"""Parse the detail sheet of a subscription, which the landing page opens for a subscription tile."""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from amazon_subscriptions.parse import selectors
from amazon_subscriptions.parse.util import Html, attr_of, check_page, soup_of, text_of


@dataclass(frozen=True)
class BackupItem:
    """The backup product of a subscription, sent if the subscribed product is not available."""

    asin: str
    title: str | None = None


def parse_subscription_detail(html: Html, page: str | None = None) -> BackupItem | None:
    """The backup product of a subscription's detail sheet, ``None`` if it has none."""
    soup = soup_of(html)
    check_page(soup, page)
    link = soup.select_one(selectors.SUBSCRIPTION_DETAIL_BACKUP_LINK)
    query = parse_qs(urlparse(attr_of(link, "href") or "").query)
    asin = next(iter(query.get("ASIN", [])), None)
    if link is None or not asin:
        return None
    return BackupItem(asin=asin, title=text_of(link.select_one(selectors.SUBSCRIPTION_DETAIL_BACKUP_TITLE)))
