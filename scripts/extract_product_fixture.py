#!/usr/bin/env python
"""Reduce a product page (/dp/<ASIN>) to what the price parser reads, so it can be committed as a test fixture.

Product pages are several MB and full of personal data (delivery address, recommendations, order history). Only the
title, the availability and the price blocks are kept. The title is replaced, the ASIN gets a fake value and offer,
merchant and session IDs are removed.

Usage:

    python scripts/extract_product_fixture.py raw/B0XXXXXXXX.html tests/fixtures/de/product.html \\
        --asin B0TESTP001 --title "Testprodukt 01"

Check the output for personal data before committing it.
"""

import argparse
import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment

KEEP = ["#productTitle", "#availability", "#corePriceDisplay_desktop_feature_div", "#corePrice_feature_div"]
#: Attributes with IDs of offers, merchants or sessions
DROP_ATTRIBUTES = re.compile(r"data-csa-c-(?:item-id|id|merchant-id|offer-id|session-id)|data-a-state|k-.*")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("page")
    parser.add_argument("output")
    parser.add_argument("--asin", required=True, help="The fake ASIN")
    parser.add_argument("--title", required=True, help="The fake title")
    args = parser.parse_args()

    raw = Path(args.page).read_text(encoding="utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    asin = re.search(r"/dp/([A-Z0-9]{10})", str(soup.select_one("link[rel=canonical]")) or "")
    parts = [soup.select_one(selector) for selector in KEEP]

    body = BeautifulSoup("<html><body></body></html>", "html.parser")
    assert body.body is not None
    for part in parts:
        if part is None:
            continue
        for tag in part.find_all(["style", "script"]):
            tag.decompose()
        for comment in part.find_all(string=lambda s: isinstance(s, Comment)):
            comment.extract()
        for tag in [part, *part.find_all(True)]:
            for name in [n for n in tag.attrs if DROP_ATTRIBUTES.fullmatch(n)]:
                del tag[name]
        if part.get("id") == "productTitle":
            part.string = args.title
        body.body.append(part)

    html = body.decode(formatter="html5")
    if asin:
        html = html.replace(asin.group(1), args.asin)
    Path(args.output).write_text(re.sub(r"\n\s*\n+", "\n", html) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
