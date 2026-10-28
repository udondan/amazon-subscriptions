#!/usr/bin/env python
"""Scan pages for text that looks like personal data.

The anonymizer only replaces what it recognizes, so this scan looks for what it may have missed: e-mail addresses,
phone numbers, order and session numbers, customer IDs, names after "Hello" or "Deliver to", postcodes next to a town
and product names in links. It cannot be complete and reports false positives, so it only warns. Always check the
pages yourself as well.

It also has the replacements both fixture scripts apply to every page.

Findings are printed masked, never in full, so the output can be shared.

Usage:

    python scripts/privacy_scan.py tests/fixtures/de/*.html
"""

import argparse
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from amazonorders.constants import Constants
from bs4 import BeautifulSoup

#: Values the anonymizers write themselves
FAKE_VALUES = {
    "Max Mustermann",
    "Musterstraße 1",
    "10115 Berlin",
    "kunde@example.com",
    "A1B2C3D4E5F6G7",
    "000-0000000-0000000",
}
#: Public IDs that look like customer IDs: the marketplace IDs of the Amazon sites and Amazon EU as a seller
PUBLIC_IDS = {
    "A1PA6795UKMFR9", "A3JWKAKR8XB7XF", "ATVPDKIKX0DER", "A1F83G8C2ARO7P", "A13V1IB3VIYZZH", "A1RKKUPIHCS9HS",
    "APJ6JRA9NG5V4", "A1805IZSGTT6HS", "A2NODRKZP88ZB9", "A1C3SOZRARQ6R3", "A2Q3Y263D00KWC", "A1AM78C64UM0Y8",
    "A2EUQ1WTGCTBG2", "A39IBJ37TRP1C6", "A21TJRUUN4KGV", "A1VC38T7YXB528", "A19VAU5U5O7RUS", "A17E79C6D8DWNP",
    "A2VIGQ35RCS4UG", "ARBP9OOSHTCHU", "A33AVAJ2PDY3EV", "AE08WJ6YKNBMC", "AMEN7PMS3EDWL", "A28R8C7NBKEWEA",
}  # fmt: skip
CHECKS = [
    ("e-mail address", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.IGNORECASE)),
    (
        "phone number",
        re.compile(r"(?<![\w.,/-])(?:\+\d{1,3}[ \xa0]?|0)\d{2,5}[ \xa0/-]?\d{3,}(?:[ \xa0-]\d{2,})*(?![\w.,/-])"),
    ),
    ("order or session number", re.compile(Constants.ORDER_NUMBER_REGEX)),
    ("customer ID", re.compile(r"(?<![A-Za-z0-9])A[0-9A-Z]{11,13}(?![A-Za-z0-9])")),
    (
        "name",
        re.compile(
            r"\b(?:Hello|Hi|Deliver(?:ing)? to|Ship to|Recipient)\b[,:]?[ \xa0]+"
            r"([A-ZÄÖÜ][\w.'-]+(?:[ \xa0][A-ZÄÖÜ][\w.'-]+)*)"
        ),
    ),
    (
        "postcode and town",
        re.compile(
            r"(?<![\w-])(?:\d{4,5}|[A-Z]{1,2}\d[A-Z\d]?[ \xa0]\d[A-Z]{2})"
            r"[ \xa0]+[A-ZÄÖÜ][a-zäöüß]{2,}(?:[ -][A-ZÄÖÜ][a-zäöüß]+)?\b"
        ),
    ),
    ("product name in a link", re.compile(r"(?<=[^/])/(?!-/)(?![a-z]{2}(?:_[A-Z]{2})?/)([^/\"'\s?#<>]+)/dp/")),
]
#: Words after "Hello" or "Deliver to" that are no names
NOT_NAMES = {"Sign", "Select", "Your", "Amazon", "Choose", "Update", "Check", "Prime"}


#: Session IDs, e.g. in the tracking pixels, which have the format of order numbers
SESSION_ID_RE = re.compile(r"(?<![\w-])\d{3}-\d{7}-\d{7}(?![\w-])")
#: The product name in a product link, e.g. "/Product-Name/dp/B0..." or "/-/en/Product-Name/dp/B0..."
LINK_TITLE_RE = re.compile(r"(?<=[^/])/(?!-/)(?![a-z]{2}(?:_[A-Z]{2})?/)[^/\"'\s?#<>]+/(?=dp/|gp/product/)")


def remove_session_ids(html: str) -> str:
    return SESSION_ID_RE.sub("000-0000000-0000000", html)


def remove_link_titles(html: str) -> str:
    """Remove the product names from product links, which keep the ASIN only."""
    return LINK_TITLE_RE.sub("/", html)


class Finding(NamedTuple):
    kind: str
    masked: str
    context: str


def mask(value: str) -> str:
    return f"{value[:2]}…({len(value)} chars)"


def _texts(html: str) -> Iterator[str]:
    """The visible text and the attribute values, without scripts and styles, whose numbers are mostly IDs."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    yield re.sub(r"\s+", " ", soup.get_text(" "))
    for tag in soup.find_all(True):
        for value in tag.attrs.values():
            yield " ".join(value) if isinstance(value, list) else str(value)


def scan(html: str) -> list[Finding]:
    findings: dict[tuple[str, str], Finding] = {}
    for text in _texts(html):
        for kind, regex in CHECKS:
            for match in regex.finditer(text):
                value = match.group(match.lastindex or 0)
                before = text[max(0, match.start() - 40) : match.start()]
                if _ignored(kind, value, match.group(0), before) or (kind, value) in findings:
                    continue
                context = before + text[match.start() : match.end() + 20].replace(value, "<X>")
                findings[(kind, value)] = Finding(kind, mask(value), context)
    return list(findings.values())


def _ignored(kind: str, value: str, whole: str, before: str) -> bool:
    if any(fake in whole for fake in FAKE_VALUES) or "TEST" in value or "example." in value:
        return True
    if kind == "customer ID":
        return (
            value in PUBLIC_IDS
            or not any(c.isdigit() for c in value[1:])
            or re.search(r"promotionId=$", before, re.IGNORECASE) is not None
        )
    if kind == "name":
        return value.split()[0] in NOT_NAMES
    if kind == "order or session number":
        return set(value) <= {"0", "-"}
    if kind == "postcode and town":
        # A year before a word, or the fake card digits before a word
        return re.match(r"(?:19|20)\d\d\b|1234\b", whole) is not None
    return False


def report(path: str | Path, html: str | None = None) -> int:
    """Print the findings of one page and return how many there were."""
    if html is None:
        html = Path(path).read_text(encoding="utf-8")
    findings = scan(html)
    for finding in findings:
        print(f"WARN {path}: possible {finding.kind} {finding.masked}: …{finding.context}…")
    return len(findings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pages", nargs="+", help="The pages to scan")
    args = parser.parse_args()
    count = sum(report(page) for page in args.pages)
    print(f"{count} possible personal data found." if count else "Nothing found. Check the pages yourself as well.")
    sys.exit(1 if count else 0)


if __name__ == "__main__":
    main()
