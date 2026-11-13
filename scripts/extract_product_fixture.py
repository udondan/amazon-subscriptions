#!/usr/bin/env python
"""Reduce product pages (/dp/<ASIN>) to what the price parser reads, so they can be committed as test fixtures.

Product pages are several MB and full of personal data (delivery address, recommendations, order history). Only the
title, the availability, the price blocks of all offers and, as blocks the parser must not read, the variants, the
comparison widget and one sponsored product are kept. The titles of the product and of the other products are
replaced, the ASINs, seller names and seller IDs get fake values and offer, merchant, ad and session IDs are removed.

Each page is given as RAW or RAW:NAME. Without NAME, the output is named after the fake ASIN. The fake ASIN is taken
from --asin-map, which scripts/anonymize_fixtures.py writes, so it matches the ASIN of the subscription in the other
fixtures. Pages without an entry get B0TESTP001, B0TESTP002 and so on.

Examples:

    # The pages scripts/anonymize_fixtures.py listed, named by what they show
    python scripts/extract_product_fixture.py --output-dir tests/fixtures/de --asin-map raw/asin-map.json \\
        raw/B0XXXXXXXX_0.html:product.html raw/B0YYYYYYYY_0.html:product-list-price.html

    # A single page without a map
    python scripts/extract_product_fixture.py --output-dir tests/fixtures/de raw/B0XXXXXXXX_0.html:product.html

The page can be the HTML as Amazon sends it or the rendered DOM of a browser; the latter also has the prices of the
variants. For each page, the script prints what the parser reads from it, so you can tell the pages apart, and warns
about text that looks like personal data. Check the output yourself before committing it.
"""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from fixture_html import SELLER_ID_RE, append, hide_titles, replace_text, shell
from privacy_scan import remove_link_titles, remove_session_ids, report

from amazon_subscriptions.locales import get_locale
from amazon_subscriptions.parse import parse_product_page, selectors

HTML_PARSER = "html.parser"
#: Blocks kept as they are
KEEP = [selectors.PRODUCT_TITLE, "#availability"]
#: Blocks of the buybox offers, kept inside an empty copy of their accordion row
OFFER_ROW = "#buyBoxAccordion > [id^='newAccordionRow'], #buyBoxAccordion > #snsAccordionRowMiddle"
OFFER_ROW_KEEP = ["#newAccordionCaption_feature_div", "#corePrice_feature_div", "#merchantInfoFeature_feature_div"]
#: The block of an offer: in the accordion rows or, on pages with a single offer, in the buybox itself
OFFER = "#corePrice_feature_div"
#: Seller names: the text of the merchant info of an offer row and, on pages loaded without session, its link
SELLER_NAMES = [
    "[offer-display-feature-name='desktop-merchant-info-collapsed'] .offer-display-feature-text-message",
    "#sellerProfileTriggerId",
]
#: Texts of the seller elements that are no seller names, kept as they are
NOT_SELLER_NAMES = {"Amazon"}
#: Price displays of the offers, kept inside an empty copy of their wrapper, which hides all but the selected one
PRICE_DISPLAY = "#corePriceDisplay_desktop_feature_div"
#: Blocks with prices of other products
FOREIGN = ["#twister_feature_div li[data-asin]", "[data-feature-name='sims-productBundle']"]
SPONSORED = "[id^='sp_detail_'][data-asin]"
ASIN_RE = re.compile(r"(?<![A-Z0-9])B0[0-9A-Z]{8}(?![A-Z0-9])")
CANONICAL_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")
#: The --debug output names product pages after the requested ASIN, e.g. B0XXXXXXXX_0.html
REQUESTED_ASIN_RE = re.compile(r"([A-Z0-9]{10})_\d+\.html$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pages", nargs="+", metavar="RAW[:NAME]", help="a raw product page and the name of its output")
    parser.add_argument("--output-dir", required=True, help="where to write the pages, e.g. tests/fixtures/de")
    parser.add_argument("--asin-map", help="JSON file of real to fake ASINs, as written by anonymize_fixtures.py")
    args = parser.parse_args()

    asin_map: dict[str, str] = {}
    if args.asin_map:
        asin_map = json.loads(Path(args.asin_map).read_text(encoding="utf-8"))
    warnings = 0
    for number, page in enumerate(args.pages, 1):
        raw, _, name = page.partition(":")
        requested = REQUESTED_ASIN_RE.match(Path(raw).name)
        html, fake_asin = extract(
            Path(raw).read_text(encoding="utf-8"), number, asin_map, requested.group(1) if requested else None
        )
        output = Path(args.output_dir) / (name or f"product-{fake_asin}.html")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html, encoding="utf-8")
        print(f"ok   {output}: {_summary(html)}")
        warnings += report(output, html)
    if warnings:
        print(f"{warnings} possible personal data found, check the lines starting with WARN.")


def extract(raw_html: str, number: int, asin_map: dict[str, str], requested: str | None = None) -> tuple[str, str]:
    """The reduced page and the fake ASIN of its product.

    ``requested`` is the ASIN the page was requested with, which the --debug output names the file after. Amazon may
    answer with the page of another variant, whose ASIN is not in the map.
    """
    soup = BeautifulSoup(raw_html, HTML_PARSER)
    canonical = soup.select_one("link[rel=canonical]")
    canonical_url = str(canonical.get("href", "")) if canonical else ""
    found = CANONICAL_ASIN_RE.search(canonical_url)
    asin = found.group(1) if found else None
    fake_asin = next((asin_map[a] for a in (requested, asin) if a in asin_map), "") or f"B0TESTP{number:03}"
    title = soup.select_one(selectors.PRODUCT_TITLE)
    seller_names = (tag.get_text(strip=True) for selector in SELLER_NAMES for tag in soup.select(selector))
    sellers = list(dict.fromkeys(name for name in seller_names if name and name not in NOT_SELLER_NAMES))

    body = _reduce(soup, canonical_url, fake_asin)
    _replace_names(body, title, sellers, number)
    return _replace_ids(body.decode(formatter="html5"), asin, fake_asin), fake_asin


def _reduce(soup: BeautifulSoup, canonical_url: str, fake_asin: str) -> BeautifulSoup:
    """A page with only the blocks the parser reads, moved out of ``soup``."""
    body = BeautifulSoup("<html><body></body></html>", HTML_PARSER)
    if body.body is None:
        raise ValueError("The empty page has no body")
    if canonical_url:
        # Only the site and the fake ASIN are kept, the summary reads the site from it
        site = urlparse(canonical_url)
        link = body.new_tag(
            "link", attrs={"rel": "canonical", "href": f"{site.scheme}://{site.netloc}/dp/{fake_asin}"}
        )
        body.body.append(link)
    for selector in KEEP:
        append(body.body, soup.select_one(selector))
    for display in soup.select(PRICE_DISPLAY):
        wrapper = display.find_parent(id=re.compile(r"^apex_desktop_"))
        append(body.body, shell(body, wrapper, display) if wrapper else display)
    for row in soup.select(OFFER_ROW):
        # A row has a collapsed and an expanded merchant info with the same id
        parts = [part for selector in OFFER_ROW_KEEP for part in row.select(selector)]
        append(body.body, shell(body, row, *parts))
    # The offers of the rows were moved above, so these are the ones outside an accordion
    for offer in soup.select(OFFER):
        append(body.body, offer)
    _append_foreign(body.body, soup)
    return body


def _append_foreign(parent: Tag, soup: BeautifulSoup) -> None:
    """Append the blocks with prices of other products, without their titles."""
    foreign = [part for selector in FOREIGN for part in soup.select(selector)]
    foreign.append(next((t for t in soup.select(SPONSORED) if t.find(class_="a-text-price")), None))
    titles: dict[str, str] = {}
    for part in foreign:
        if part is not None:
            hide_titles(part, titles)
        append(parent, part)


def _replace_names(body: BeautifulSoup, title: Tag | None, sellers: list[str], number: int) -> None:
    """Replace the product title and the seller names."""
    # Replaced in the tree, as the decoded page writes some characters as entities, e.g. "&amp;" for "&"
    kept_title = body.select_one(selectors.PRODUCT_TITLE)
    if kept_title is not None:
        kept_title.string = f"Product page {number:02}"
    if title is not None:
        replace_text(body, title.get_text(strip=True), f"Product page {number:02}")
    for i, seller in enumerate(sellers, 1):
        replace_text(body, seller, f"Test seller {i:02}")


def _replace_ids(html: str, asin: str | None, fake_asin: str) -> str:
    """Replace the seller IDs and ASINs, and remove the session IDs."""
    # Seller IDs are only kept in links, whose other query parameters are removed
    seller_ids: dict[str, str] = {}
    html = SELLER_ID_RE.sub(lambda m: seller_ids.setdefault(m.group(0), f"A0TESTSELLER{len(seller_ids) + 1:02}"), html)
    html = remove_session_ids(remove_link_titles(html))
    if asin:
        html = html.replace(asin, fake_asin)
    # Seeded with the fake page ASIN, which matches the pattern too
    fake_asins = {fake_asin: fake_asin}
    html = ASIN_RE.sub(lambda m: fake_asins.setdefault(m.group(0), f"B0TESTX{len(fake_asins):03}"), html)
    return re.sub(r"\n\s*\n+", "\n", html) + "\n"


def _summary(html: str) -> str:
    """What the parser reads from a page, to tell the pages apart."""
    site = re.search(r'href="https://www\.(amazon\.[a-z.]+)/dp/', html)
    try:
        prices = parse_product_page(html, get_locale(site.group(1) if site else "amazon.com"))
    except Exception as error:
        return f"not readable: {error}"
    parts = [f"price {prices.price}" if prices.price is not None else "no price"]
    if prices.list_price is not None:
        kind = prices.list_price_type.value if prices.list_price_type else "?"
        source = prices.list_price_source.value if prices.list_price_source else "?"
        parts.append(f"list price {prices.list_price} ({kind}, from {source})")
    if prices.unit_price is not None:
        parts.append(f"unit price {prices.unit_price} per {prices.unit_price_unit}")
    if prices.alternative_offer is not None:
        parts.append("alternative offer")
    return ", ".join(parts)


if __name__ == "__main__":
    main()
