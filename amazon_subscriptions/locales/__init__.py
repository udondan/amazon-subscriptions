from urllib.parse import urlparse

from amazon_subscriptions.exceptions import SubscriptionsError
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.locales.de import DeSubscriptionLocale

#: The locale of each supported storefront, keyed by the TLD suffix that follows ``amazon.``.
LOCALES_BY_TLD: dict[str, type[SubscriptionLocale]] = {
    "de": DeSubscriptionLocale,
}


def tld_of(domain_or_url: str) -> str:
    """The TLD suffix of a storefront, e.g. ``de`` for ``amazon.de`` or ``https://www.amazon.de``."""
    host = urlparse(domain_or_url).hostname if "://" in domain_or_url else domain_or_url
    host = (host or "").lower()
    if "amazon." not in host:
        raise SubscriptionsError(f"{domain_or_url!r} is not an Amazon storefront.")
    return host.split("amazon.", 1)[1]


def get_locale(domain_or_url: str) -> SubscriptionLocale:
    """The locale of a storefront, given by domain (``amazon.de``) or base URL (``https://www.amazon.de``)."""
    tld = tld_of(domain_or_url)
    if tld not in LOCALES_BY_TLD:
        raise SubscriptionsError(
            f"amazon.{tld} is not supported yet, supported are: {', '.join('amazon.' + t for t in LOCALES_BY_TLD)}."
        )
    return LOCALES_BY_TLD[tld]()


__all__ = ["LOCALES_BY_TLD", "SubscriptionLocale", "get_locale", "tld_of"]
