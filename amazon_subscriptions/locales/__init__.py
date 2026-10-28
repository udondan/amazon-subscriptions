from urllib.parse import urlparse

from amazonorders.constants import Constants
from amazonorders.region_data import REGION_SITES

from amazon_subscriptions.exceptions import SubscriptionsError
from amazon_subscriptions.locales.base import SubscriptionLocale
from amazon_subscriptions.locales.en import EnglishSubscriptionLocale

#: ISO 4217 code of the currency of each Amazon site, keyed by the TLD suffix that follows ``amazon.``.
#:
#: amazon-orders only knows the symbol a site shows its prices with, and ``$`` alone does not tell US, Canadian and
#: Australian dollars apart. The pages never show the code.
SITE_CURRENCIES: dict[str, str] = {
    "ae": "AED",
    "ca": "CAD",
    "co.jp": "JPY",
    "co.uk": "GBP",
    "co.za": "ZAR",
    "com": "USD",
    "com.au": "AUD",
    "com.be": "EUR",
    "com.br": "BRL",
    "com.mx": "MXN",
    "com.tr": "TRY",
    "de": "EUR",
    "eg": "EGP",
    "es": "EUR",
    "fr": "EUR",
    "ie": "EUR",
    "in": "INR",
    "it": "EUR",
    "nl": "EUR",
    "pl": "PLN",
    "sa": "SAR",
    "se": "SEK",
    "sg": "SGD",
}


def tld_of(domain_or_url: str) -> str:
    """The TLD suffix of a storefront, e.g. ``de`` for ``amazon.de`` or ``https://www.amazon.de``."""
    host = urlparse(domain_or_url).hostname if "://" in domain_or_url else domain_or_url
    host = (host or "").lower()
    if "amazon." not in host:
        raise SubscriptionsError(f"{domain_or_url!r} is not an Amazon storefront.")
    return host.split("amazon.", 1)[1]


def get_locale(domain_or_url: str) -> SubscriptionLocale:
    """The locale of a storefront, given by domain (``amazon.de``) or base URL (``https://www.amazon.de``).

    Every storefront that offers its pages in English is supported, as amazon-orders requests them in English.

    :raises SubscriptionsError: If the storefront is not known or offers no English pages.
    """
    tld = tld_of(domain_or_url)
    site = REGION_SITES.get(tld)
    if site is None or tld not in SITE_CURRENCIES:
        raise SubscriptionsError(f"amazon.{tld} is not a known Amazon storefront.")
    if not site.english_locale:
        raise SubscriptionsError(
            f"amazon.{tld} does not offer its pages in English, which is the only language supported."
        )
    return EnglishSubscriptionLocale(SITE_CURRENCIES[tld], Constants.region_currency_symbol(tld))


__all__ = ["SITE_CURRENCIES", "EnglishSubscriptionLocale", "SubscriptionLocale", "get_locale", "tld_of"]
