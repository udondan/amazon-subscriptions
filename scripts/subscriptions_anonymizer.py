"""The anonymizer of scripts/anonymize_fixtures.py, which extends the one of amazon-orders for Subscribe & Save
pages. See there for what it replaces."""

import difflib
import hashlib
import hmac
import importlib.util
import os
import re

from bs4 import BeautifulSoup
from privacy_scan import remove_link_titles, remove_session_ids

from amazon_subscriptions.parse import selectors

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "anonymize_test_resources.py")
_spec = importlib.util.spec_from_file_location("anonymize_test_resources", _VENDOR)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load {_VENDOR}")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

FILLER_WORDS = [
    "Lorem",
    "ipsum",
    "dolor",
    "sit",
    "amet",
    "consectetur",
    "adipiscing",
    "elit",
    "sed",
    "do",
    "eiusmod",
    "tempor",
    "incididunt",
    "ut",
    "labore",
    "et",
    "dolore",
    "magna",
    "aliqua",
    "enim",
    "minim",
    "veniam",
    "quis",
    "nostrud",
    "exercitation",
    "ullamco",
    "laboris",
    "nisi",
    "aliquip",
    "commodo",
    "consequat",
    "duis",
    "aute",
    "irure",
    "reprehenderit",
    "voluptate",
    "velit",
    "esse",
]
# A title counts as a variant of a known title if this share of its words line up
TITLE_MATCH_RATIO = 0.5

TITLE_SELECTORS = [
    "[data-edit-url] .a-truncate-full",  # subscription tiles
    ".a-truncate-full",  # recommendations
    "[data-testid='product-title']",  # delivery pages
    ".productInformation a[href*='/dp/']",  # subscription detail sheet (other links there are UI text)
    # The backup product on the detail sheet
    f"{selectors.SUBSCRIPTION_DETAIL_BACKUP_LINK} {selectors.SUBSCRIPTION_DETAIL_BACKUP_TITLE}",
]
IMAGE_ALT_MIN_LENGTH = 15
EXTRA_ASIN_REGEXES = [
    re.compile(r"subAsin=([A-Z0-9]{10})\b"),
    re.compile(r"data-asin=\"([A-Z0-9]{10})\""),
    re.compile(r"\bASIN=([A-Z0-9]{10})\b"),
]
SUBSCRIPTION_ID_REGEX = re.compile(r"SNS[A-Z]\d_[A-Z0-9]{8,}")
BUNDLE_ID_REGEX = re.compile(r"(deliveryBundleId(?:=|%3D|\"\s*:\s*\"))([A-Za-z0-9_-]{6,})")
SHIP_ID_REGEX = re.compile(r"(?:shipId(?:=|%3D)|\"shippingIds\"\s*:\s*\"|shipId\"\s*:\s*\")([a-z0-9]{8,16})\b")
FAKE_SHIP_ID = "testshipid01"
ACP_TOKEN_REGEX = re.compile(r"\b(?:tok|rid)=([^;\"&]{8,})")
#: Address blocks of delivery pages and the subscription detail sheet, read line by line
ADDRESS_SELECTORS = [
    "[data-testid='address-content']",
    "[data-testid='delivery-address']",
    ".addressInfo span.a-color-tertiary",
]


def _words(text: str) -> list[str]:
    return re.sub(r"\s+", " ", text).strip().split(" ")


class SubscriptionsAnonymizer(base.Anonymizer):  # type: ignore[name-defined,misc]
    def __init__(self, rules: dict) -> None:
        super().__init__(rules)
        # Known titles as word lists, with their fake word lists
        self.title_bases: list[tuple[list[str], list[str]]] = []
        self.subscription_ids: dict[str, str] = {}
        self.bundle_ids: dict[str, str] = {}

    def _digest(self, value: str) -> str:
        return hmac.new(self.salt, value.encode("utf-8"), hashlib.sha256).hexdigest().upper()

    def _filler(self, word: str) -> str:
        return FILLER_WORDS[int(self._digest(word), 16) % len(FILLER_WORDS)]

    def _new_fake_title(self, words: list[str]) -> list[str]:
        number = len(self.title_bases) + 1
        fake = ["Product", f"{number:02d}"] + [
            FILLER_WORDS[(i + number) % len(FILLER_WORDS)] for i in range(max(0, len(words) - 2))
        ]
        return fake[: max(len(words), 2)]

    def _fake_title(self, words: list[str]) -> list[str]:
        best, best_ratio = None, 0.0
        for known, fake in self.title_bases:
            ratio = difflib.SequenceMatcher(None, known, words).ratio()
            # A shortened title (a prefix of a known one) matches however short it is
            if words == known[: len(words)] and len(words) >= 2:
                ratio = 1.0
            if ratio > best_ratio:
                best, best_ratio = (known, fake), ratio
        if best is None or best_ratio < TITLE_MATCH_RATIO:
            fake = self._new_fake_title(words)
            self.title_bases.append((words, fake))
            return fake
        known, known_fake = best
        result: list[str] = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, known, words).get_opcodes():
            if op == "equal":
                result.extend(known_fake[i1:i2])
            elif op in ("replace", "insert"):
                result.extend(self._filler(w) for w in words[j1:j2])
        return result

    def _add_product_title(self, text: str) -> None:
        title = re.sub(r"\s+", " ", text).strip()
        if len(title) >= 4 and title not in self.titles:
            self.titles[title] = " ".join(self._fake_title(_words(title)))
            self.sensitive.add(title)

    def _collect_product_titles(self, soup: BeautifulSoup) -> None:
        for selector in TITLE_SELECTORS:
            for tag in soup.select(selector):
                self._add_product_title(tag.get_text(" "))
        for tag in soup.select("img[alt]"):
            alt = str(tag["alt"])
            if len(alt) >= IMAGE_ALT_MIN_LENGTH:
                self._add_product_title(alt)

    def _collect_asins(self, raw_html: str) -> None:
        super()._collect_asins(raw_html)
        for regex in EXTRA_ASIN_REGEXES:
            for asin in regex.findall(raw_html):
                if asin not in self.asins and not asin.isalpha():
                    self.asins[asin] = f"B0TEST{len(self.asins) + 1:04d}"
                    self.sensitive.add(asin)

    def collect_identifiers(self, html: str) -> None:
        super().collect_identifiers(html)
        for sub_id in SUBSCRIPTION_ID_REGEX.findall(html):
            if sub_id not in self.subscription_ids:
                self.subscription_ids[sub_id] = sub_id[:6] + self._digest(sub_id)[: len(sub_id) - 6]
                self.sensitive.add(sub_id)
        for _, bundle_id in BUNDLE_ID_REGEX.findall(html):
            if bundle_id not in self.bundle_ids:
                self.bundle_ids[bundle_id] = self._digest(bundle_id)[: len(bundle_id)].lower()
                self.sensitive.add(bundle_id)
        for ship_id in SHIP_ID_REGEX.findall(html):
            if ship_id != FAKE_SHIP_ID:
                self.replace.append({"find": ship_id, "replace": FAKE_SHIP_ID})
                self.sensitive.add(ship_id)
        self.sensitive.update(ACP_TOKEN_REGEX.findall(html))

    def collect_address_rules(self, soup: BeautifulSoup) -> None:
        super().collect_address_rules(soup)
        known = {rule["find"] for rule in self.replace}
        for selector in ADDRESS_SELECTORS:
            for tag in soup.select(selector):
                for line in tag.stripped_strings:
                    line = re.sub(r"\s+", " ", line)
                    self._add_address(line, base._fake_address_part(line), known)

    def clean_text(self, html: str) -> str:
        for original, fake in sorted(self.subscription_ids.items(), key=lambda t: len(t[0]), reverse=True):
            html = html.replace(original, fake)
        for original, fake in self.bundle_ids.items():
            html = html.replace(original, fake)
        # Upstream only accepts "%2C" directly before an ASIN, recommendation links also use "%7C" ("|")
        for asin, fake in self.asins.items():
            html = re.sub(r"(?<=%[0-9A-Fa-f]{2})" + asin + r"(?![A-Za-z0-9])", fake, html)
        # Upstream gives session IDs fake values as order IDs, which the scan cannot tell from real ones
        return remove_session_ids(super().clean_text(remove_link_titles(html)))
