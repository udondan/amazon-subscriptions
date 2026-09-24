#!/usr/bin/env python
"""Anonymize raw Subscribe & Save pages so they can be committed as test fixtures.

Builds on the anonymizer of amazon-orders (``scripts/vendor/anonymize_test_resources.py``) and adds what Subscribe &
Save pages need:

* Product titles are replaced word by word, aligned with the subscription titles. Delivery pages show shortened or
  slightly different titles, and the fixtures must keep that relation, otherwise matching cannot be tested.
* ASINs, subscription IDs, delivery bundle IDs and shipping IDs get stable fake values.
* ACP widget tokens are redacted.
* Prices, quantities, intervals and dates are kept (no ``date_shift_days`` or ``amount_factor``).

Usage:

    python scripts/anonymize_fixtures.py --rules /tmp/sns-raw/rules.json \\
        --extra-sensitive-file ~/.config/amazonorders/cookies.json \\
        --output-dir tests/fixtures/de raw/auto-deliveries_0.html:landing.html ...

The rules file has the same format as the one of amazon-orders and must never be committed.
Subscription tiles must come first on the command line, so their titles define the fake titles.
"""

import difflib
import hashlib
import hmac
import importlib.util
import json
import os
import re
import sys
from typing import Dict, List, Tuple

from bs4 import BeautifulSoup

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "anonymize_test_resources.py")
_spec = importlib.util.spec_from_file_location("anonymize_test_resources", _VENDOR)
assert _spec and _spec.loader
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

FILLER_WORDS = ["Lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit", "sed", "do",
                "eiusmod", "tempor", "incididunt", "ut", "labore", "et", "dolore", "magna", "aliqua", "enim",
                "minim", "veniam", "quis", "nostrud", "exercitation", "ullamco", "laboris", "nisi", "aliquip",
                "commodo", "consequat", "duis", "aute", "irure", "reprehenderit", "voluptate", "velit", "esse"]
# A title counts as a variant of a known title if this share of its words line up
TITLE_MATCH_RATIO = 0.5

TITLE_SELECTORS = [
    "[data-edit-url] .a-truncate-full",  # subscription tiles
    ".a-truncate-full",  # recommendations
    "[data-testid='product-title']",  # delivery pages
    ".productInformation a[href*='/dp/']",  # subscription detail sheet (other links there are UI text)
]
IMAGE_ALT_MIN_LENGTH = 15
EXTRA_ASIN_REGEXES = [re.compile(r"subAsin=([A-Z0-9]{10})\b"), re.compile(r"data-asin=\"([A-Z0-9]{10})\""),
                      re.compile(r"\bASIN=([A-Z0-9]{10})\b")]
SUBSCRIPTION_ID_REGEX = re.compile(r"SNS[A-Z][0-9]_[A-Z0-9]{8,}")
BUNDLE_ID_REGEX = re.compile(r"(deliveryBundleId(?:=|%3D|\"\s*:\s*\"))([A-Za-z0-9_-]{6,})")
SHIP_ID_REGEX = re.compile(r"(?:shipId(?:=|%3D)|\"shippingIds\"\s*:\s*\"|shipId\"\s*:\s*\")([a-z0-9]{8,16})\b")
FAKE_SHIP_ID = "testshipid01"
ACP_TOKEN_REGEX = re.compile(r"\b(?:tok|rid)=([^;\"&]{8,})")
ADDRESS_TESTIDS = ["[data-testid='address-content']", "[data-testid='delivery-address']"]


def _words(text: str) -> List[str]:
    return re.sub(r"\s+", " ", text).strip().split(" ")


class SubscriptionsAnonymizer(base.Anonymizer):  # type: ignore[name-defined,misc]
    def __init__(self, rules: Dict) -> None:
        super().__init__(rules)
        # Known titles as word lists, with their fake word lists
        self.title_bases: List[Tuple[List[str], List[str]]] = []
        self.subscription_ids: Dict[str, str] = {}
        self.bundle_ids: Dict[str, str] = {}

    def _digest(self, value: str) -> str:
        return hmac.new(self.salt, value.encode("utf-8"), hashlib.sha256).hexdigest().upper()

    def _filler(self, word: str) -> str:
        return FILLER_WORDS[int(self._digest(word), 16) % len(FILLER_WORDS)]

    def _new_fake_title(self, words: List[str]) -> List[str]:
        number = len(self.title_bases) + 1
        fake = ["Testartikel", f"{number:02d}"] + [FILLER_WORDS[(i + number) % len(FILLER_WORDS)]
                                                   for i in range(max(0, len(words) - 2))]
        return fake[:max(len(words), 2)]

    def _fake_title(self, words: List[str]) -> List[str]:
        best, best_ratio = None, 0.0
        for known, fake in self.title_bases:
            ratio = difflib.SequenceMatcher(None, known, words).ratio()
            # A shortened title (a prefix of a known one) matches however short it is
            if words == known[:len(words)] and len(words) >= 2:
                ratio = 1.0
            if ratio > best_ratio:
                best, best_ratio = (known, fake), ratio
        if best is None or best_ratio < TITLE_MATCH_RATIO:
            fake = self._new_fake_title(words)
            self.title_bases.append((words, fake))
            return fake
        known, known_fake = best
        result: List[str] = []
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
                self.subscription_ids[sub_id] = sub_id[:6] + self._digest(sub_id)[:len(sub_id) - 6]
                self.sensitive.add(sub_id)
        for _, bundle_id in BUNDLE_ID_REGEX.findall(html):
            if bundle_id not in self.bundle_ids:
                self.bundle_ids[bundle_id] = self._digest(bundle_id)[:len(bundle_id)].lower()
                self.sensitive.add(bundle_id)
        for ship_id in SHIP_ID_REGEX.findall(html):
            if ship_id != FAKE_SHIP_ID:
                self.replace.append({"find": ship_id, "replace": FAKE_SHIP_ID})
                self.sensitive.add(ship_id)
        self.sensitive.update(ACP_TOKEN_REGEX.findall(html))

    def collect_address_rules(self, soup: BeautifulSoup) -> None:
        super().collect_address_rules(soup)
        known = {rule["find"] for rule in self.replace}
        for selector in ADDRESS_TESTIDS:
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
        return super().clean_text(html)


def main() -> None:
    args = base.parse_args()
    with open(os.path.expanduser(args.rules), encoding="utf-8") as f:
        anonymizer = SubscriptionsAnonymizer(json.load(f))
    # Reuse the upstream loader only for the extra sensitive values (e.g. the cookie jar)
    anonymizer.sensitive.update(base.load_anonymizer(args.rules, args.extra_sensitive_file).sensitive)

    pairs = [page.split(":") for page in args.pages]
    soups = [base.read_page(anonymizer, raw_path) for raw_path, *_ in pairs]
    written = [base.write_page(anonymizer, soup, args.output_dir, out_rel)
               for (_, out_rel, *_), soup in zip(pairs, soups)]

    results = [base.check_page(anonymizer, out_path) for out_path in written]
    print(f"{len(anonymizer.titles)} titles, {len(anonymizer.asins)} ASINs, "
          f"{len(anonymizer.subscription_ids)} subscription IDs, {len(anonymizer.bundle_ids)} bundle IDs replaced, "
          f"{len(anonymizer.sensitive)} sensitive values checked.")
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
