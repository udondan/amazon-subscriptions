#!/usr/bin/env python
"""Reduce a product page (/dp/<ASIN>) to what the price parser reads, so it can be committed as a test fixture.

Product pages are several MB and full of personal data (delivery address, recommendations, order history). Only the
title, the availability, the price blocks of all offers and, as blocks the parser must not read, the variants, the
comparison widget and one sponsored product are kept. The title is replaced, the ASINs and seller names get fake values
and offer, merchant, ad and session IDs are removed.

Usage:

    python scripts/extract_product_fixture.py raw/B0XXXXXXXX.html tests/fixtures/de/product.html \\
        --asin B0TESTP001 --title "Testprodukt 01"

The page can be the HTML as Amazon sends it or the rendered DOM of a browser; the latter also has the prices of the
variants. Check the output for personal data before committing it.
"""

import argparse
import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Tag

#: Blocks kept as they are
KEEP = ["#productTitle", "#availability"]
#: Blocks of the buybox offers, kept inside an empty copy of their accordion row
OFFER_ROW = "#buyBoxAccordion > [id^='newAccordionRow']"
OFFER_ROW_KEEP = ["#newAccordionCaption_feature_div", "#corePrice_feature_div", "#merchantInfoFeature_feature_div"]
#: Price displays of the offers, kept inside an empty copy of their wrapper, which hides all but the selected one
PRICE_DISPLAY = "#corePriceDisplay_desktop_feature_div"
#: Blocks with prices of other products
FOREIGN = ["#twister_feature_div li[data-asin]", "[data-feature-name='sims-productBundle']"]
SPONSORED = "[id^='sp_detail_'][data-asin]"
#: Attributes with IDs of offers, merchants, ads or sessions, or with data not needed
DROP_ATTRIBUTES = re.compile(
    r"data-csa-c-(?:id|merchant-id|offer-id|session-id)|data-a-state|k-.*|data-components|data-atc-click-urls"
    r"|data-price-totals|data-a-dynamic-image|src|srcset|value|action|data-ad-.*|data-a-modal|.*pixelurl|data-adfeedbackdetails"
)
#: Classes with request IDs
DROP_CLASSES = re.compile(r"(?:pd_rd_\w+|pf_rd_\w+|content-id)-.*")
ASIN_RE = re.compile(r"(?<![A-Z0-9])B0[0-9A-Z]{8}(?![A-Z0-9])")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("page")
    parser.add_argument("output")
    parser.add_argument("--asin", required=True, help="The fake ASIN")
    parser.add_argument("--title", required=True, help="The fake title")
    args = parser.parse_args()

    soup = BeautifulSoup(Path(args.page).read_text(encoding="utf-8"), "html.parser")
    asin = re.search(r"/dp/([A-Z0-9]{10})", str(soup.select_one("link[rel=canonical]")) or "")
    title = soup.select_one("#productTitle")
    seller_names = (tag.get_text(strip=True) for tag in soup.select("#sellerProfileTriggerId"))
    sellers = list(dict.fromkeys(filter(None, seller_names)))

    body = BeautifulSoup("<html><body></body></html>", "html.parser")
    assert body.body is not None
    for selector in KEEP:
        _append(body.body, soup.select_one(selector))
    for display in soup.select(PRICE_DISPLAY):
        wrapper = display.find_parent(id="apex_desktop_newAccordionRow")
        _append(body.body, _shell(body, wrapper, display) if wrapper else display)
    for row in soup.select(OFFER_ROW):
        parts = [part for selector in OFFER_ROW_KEEP if (part := row.select_one(selector))]
        _append(body.body, _shell(body, row, *parts))
    for selector in FOREIGN:
        for part in soup.select(selector):
            _append(body.body, part)
    sponsored = next((t for t in soup.select(SPONSORED) if t.find(class_="a-text-price")), None)
    _append(body.body, sponsored)

    html = body.decode(formatter="html5")
    if title is not None:
        html = html.replace(title.get_text(strip=True), args.title)
    for i, seller in enumerate(sellers, 1):
        html = html.replace(seller, f"Testhändler {i:02}")
    html = re.sub(r"seller=[A-Z0-9]+", "seller=A0TESTSELLER", html)
    html = re.sub(r"\b\d{3}-\d{7}-\d{7}\b", "000-0000000-0000000", html)  # Session IDs
    if asin:
        html = html.replace(asin.group(1), args.asin)
    # Seeded with the fake page ASIN, which matches the pattern too
    fake_asins = {args.asin: args.asin}
    html = ASIN_RE.sub(lambda m: fake_asins.setdefault(m.group(0), f"B0TESTX{len(fake_asins):03}"), html)
    Path(args.output).write_text(re.sub(r"\n\s*\n+", "\n", html) + "\n", encoding="utf-8")


def _shell(body: BeautifulSoup, tag: Tag, *children: Tag) -> Tag:
    """An empty copy of ``tag`` with only its id, class and style, holding ``children``."""
    shell = body.new_tag(tag.name, attrs={k: v for k, v in tag.attrs.items() if k in ("id", "class", "style")})
    for child in children:
        shell.append(child)
    return shell


def _append(parent: Tag, part: Tag | None) -> None:
    if part is None:
        return
    for tag in part.find_all(["style", "script", "noscript", "img", "input", "svg"]):
        tag.decompose()
    for comment in part.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in [part, *part.find_all(True)]:
        for name in [n for n in tag.attrs if DROP_ATTRIBUTES.fullmatch(n)]:
            del tag[name]
        if isinstance(tag.get("class"), list):
            tag["class"] = [c for c in tag["class"] if not DROP_CLASSES.fullmatch(c)]
        if tag.get("href"):
            # Paths keep the ASIN of a link, queries only hold tracking IDs
            tag["href"] = re.sub(r"/ref=[^/?]*|\?.*", "", str(tag["href"]))
    parent.append(part)


if __name__ == "__main__":
    main()
