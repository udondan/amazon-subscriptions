#!/usr/bin/env python
"""Anonymize raw Subscribe & Save pages so they can be committed as test fixtures.

Builds on the anonymizer of amazon-orders (``scripts/vendor/anonymize_test_resources.py``) and adds what Subscribe &
Save pages need:

* Product titles are replaced word by word, aligned with the subscription titles. Delivery pages show shortened or
  slightly different titles, and the fixtures must keep that relation, otherwise matching cannot be tested.
* ASINs, subscription IDs, delivery bundle IDs and shipping IDs get stable fake values.
* ACP widget tokens are redacted.
* Prices, quantities, intervals and dates are kept (no ``date_shift_days`` or ``amount_factor``).

Not replaced: free text such as names in messages, and anything the page shows in an unknown place. After writing,
every page is checked for the sensitive values that were seen (exit code 1 if one survived) and scanned for text that
looks like personal data (printed as warnings). Always check the pages yourself as well.

Examples:

    # The output of `amazon-subscriptions --debug --output-dir raw ...`, named as the tests expect
    python scripts/anonymize_fixtures.py --from-debug-dir raw --output-dir tests/fixtures/de

    # Also replace your name where the page shows it in an unknown place
    python scripts/anonymize_fixtures.py --from-debug-dir raw --output-dir tests/fixtures/de \\
        --replace "Jane Doe=Max Mustermann" --sensitive "Jane"

    # Single pages, as RAW:NAME; subscription tiles first, so their titles define the fake titles
    python scripts/anonymize_fixtures.py --output-dir tests/fixtures/de \\
        raw/auto-deliveries_0.html:landing.html raw/index_0.html:delivery-1.html

With --from-debug-dir, the pages are sorted by their content, the product pages are listed for
scripts/extract_product_fixture.py, and the real and fake ASINs are written to asin-map.json in the debug directory.
That file is as private as the raw pages.

--rules takes a private JSON file in the format of amazon-orders (``id_salt``, ``replace``, ``sensitive``), which
must never be committed. Without it, a random salt is used, so the fake IDs differ from run to run.
"""

import argparse
import difflib
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from privacy_scan import remove_link_titles, remove_session_ids, report

from amazon_subscriptions.parse import selectors

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "anonymize_test_resources.py")
_spec = importlib.util.spec_from_file_location("anonymize_test_resources", _VENDOR)
assert _spec and _spec.loader
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
SUBSCRIPTION_ID_REGEX = re.compile(r"SNS[A-Z][0-9]_[A-Z0-9]{8,}")
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


#: The cookie jars of amazon-orders, one per site and the one all sites shared before, whose values must not survive
COOKIE_JARS = "~/.config/amazonorders/cookies*.json"
#: Files of the --debug output named by the client itself
SUBSCRIPTIONS_PAGE_RE = re.compile(r"paginate-subscriptions_(\d+)\.html")
DELIVERIES_PAGE_RE = re.compile(r"paginate-deliveries_(\d+)\.html")
DETAIL_MARKER = ".productInformation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pages", nargs="*", metavar="RAW:NAME", help="a raw page and the name of its output")
    parser.add_argument("--output-dir", required=True, help="where to write the pages, e.g. tests/fixtures/de")
    parser.add_argument("--from-debug-dir", metavar="DIR", help="take all pages from the --debug output in DIR")
    parser.add_argument("--rules", help="private JSON rules file in the format of amazon-orders, never commit it")
    parser.add_argument(
        "--sensitive", action="append", default=[], metavar="VALUE", help="a value that must not survive (repeatable)"
    )
    parser.add_argument(
        "--replace", action="append", default=[], metavar="FIND=REPLACE", help="replace a text (repeatable)"
    )
    parser.add_argument(
        "--extra-sensitive-file",
        action="append",
        metavar="FILE",
        help=f"JSON file whose values must not survive (repeatable, default: all {COOKIE_JARS})",
    )
    args = parser.parse_args()
    if not args.pages and not args.from_debug_dir:
        parser.error("give the pages as RAW:NAME or --from-debug-dir")
    if any("=" not in rule for rule in args.replace):
        parser.error("--replace takes FIND=REPLACE")
    return args


def load_rules(args: argparse.Namespace) -> dict:
    rules: dict = {"id_salt": secrets.token_hex(16)}
    if args.rules:
        rules.update(json.loads(Path(args.rules).expanduser().read_text(encoding="utf-8")))
    rules["replace"] = [*rules.get("replace", []), *({"find": f, "replace": r} for f, r in _pairs(args.replace))]
    rules["sensitive"] = [*rules.get("sensitive", []), *args.sensitive, *(f for f, _ in _pairs(args.replace))]
    return rules


def _pairs(rules: list[str]) -> list[tuple[str, str]]:
    return [(find, replace) for find, _, replace in (rule.partition("=") for rule in rules)]


def extra_sensitive_values(paths: list[str] | None) -> set[str]:
    """The values of JSON files such as the cookie jar: an object of values or a list of objects with a value."""
    if paths is None:
        jars = Path(COOKIE_JARS).expanduser()
        paths = [str(path) for path in sorted(jars.parent.glob(jars.name)) if path.is_file()]
    values: set[str] = set()
    for path in paths:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        entries = data.values() if isinstance(data, dict) else data
        entries = [entry.get("value") if isinstance(entry, dict) else entry for entry in entries]
        values.update(v for v in entries if isinstance(v, str) and len(v) >= 12)
    return values


def debug_pages(directory: str) -> tuple[list[tuple[str, str]], list[Path]]:
    """The pages of a --debug output as (raw path, output name), subscription tiles first, and the product pages."""
    landing: list[Path] = []
    subscriptions_pages: list[tuple[int, Path]] = []
    deliveries_pages: list[tuple[int, Path]] = []
    deliveries: list[Path] = []
    details: list[Path] = []
    products: list[Path] = []
    for path in sorted(Path(directory).glob("*.html"), key=_natural):
        if match := SUBSCRIPTIONS_PAGE_RE.fullmatch(path.name):
            subscriptions_pages.append((int(match.group(1)), path))
            continue
        if match := DELIVERIES_PAGE_RE.fullmatch(path.name):
            deliveries_pages.append((int(match.group(1)), path))
            continue
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        if soup.select_one(selectors.PRODUCT_TITLE):
            products.append(path)
        elif soup.select_one(selectors.SUBSCRIPTIONS_WIDGET):
            landing.append(path)
        elif soup.select_one(selectors.DELIVERY_ITEM):
            deliveries.append(path)
        elif soup.select_one(DETAIL_MARKER):
            details.append(path)
        else:
            print(f"skip {path}: not a page the tests use")
    if len(landing) != 1:
        sys.exit(
            f"Expected one landing page in {directory}, found {len(landing)}. Capture each run into a new directory."
        )
    pages = [(str(landing[0]), "landing.html")]
    pages += [(str(path), f"subscriptions-page-{index + 2}.html") for index, path in subscriptions_pages]
    pages += [(str(path), f"delivery-{number}.html") for number, path in enumerate(deliveries, 1)]
    pages += [(str(path), f"deliveries-page-{index + 2}.html") for index, path in deliveries_pages]
    pages += [(str(path), "subscription-detail.html" if len(details) == 1 else f"subscription-detail-{number}.html")
              for number, path in enumerate(details, 1)]  # fmt: skip
    return pages, products


def _natural(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.name)]


def main() -> None:
    args = parse_args()
    anonymizer = SubscriptionsAnonymizer(load_rules(args))
    anonymizer.sensitive.update(extra_sensitive_values(args.extra_sensitive_file))

    pairs = [tuple(page.split(":", 1)) for page in args.pages]
    products: list[Path] = []
    if args.from_debug_dir:
        found, products = debug_pages(args.from_debug_dir)
        pairs = [*found, *pairs]
    soups = [base.read_page(anonymizer, raw_path) for raw_path, _ in pairs]
    written = [
        base.write_page(anonymizer, soup, args.output_dir, name) for (_, name), soup in zip(pairs, soups, strict=True)
    ]

    results = [base.check_page(anonymizer, out_path) for out_path in written]
    warnings = sum(report(out_path) for out_path in written)
    print(
        f"{len(anonymizer.titles)} titles, {len(anonymizer.asins)} ASINs, "
        f"{len(anonymizer.subscription_ids)} subscription IDs, {len(anonymizer.bundle_ids)} bundle IDs replaced, "
        f"{len(anonymizer.sensitive)} sensitive values checked."
    )
    if warnings:
        print(f"{warnings} possible personal data found, check the lines starting with WARN.")
    if products:
        asin_map = Path(args.from_debug_dir) / "asin-map.json"
        asin_map.write_text(json.dumps(anonymizer.asins, indent=2), encoding="utf-8")
        print(f"\n{len(products)} product pages. Reduce the ones you need with scripts/extract_product_fixture.py:\n")
        print(f"    python scripts/extract_product_fixture.py --output-dir {args.output_dir} --asin-map {asin_map} \\")
        print("        " + " ".join(str(path) for path in products))
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
