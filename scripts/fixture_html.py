"""HTML helpers of scripts/extract_product_fixture.py, which reduce and anonymize the blocks of a product page."""

import re

from bs4 import BeautifulSoup, Comment, Tag

from amazon_subscriptions.locales import SITE_CURRENCIES, get_locale

SELLER_ID_RE = re.compile(r"(?<=[?&]seller=)[A-Z0-9]+")
#: Texts of other products at least this long are taken as titles or descriptions and replaced
MIN_TITLE_LENGTH = 25
#: An amount next to a currency sign or code; amounts in titles ("2.5 kg") stand next to a unit
_CURRENCY = rf"(?:[$£¥₠-⃏]|\b(?:{'|'.join(sorted(set(SITE_CURRENCIES.values())))})\b)"
PRICE_LIKE_RE = re.compile(rf"{_CURRENCY}\s?\d|\d\s?{_CURRENCY}")
THIS_ITEM_LABEL = get_locale("amazon.de").THIS_ITEM_LABEL
#: Attributes with IDs of offers, merchants, ads or sessions, or with data not needed
DROP_ATTRIBUTES = re.compile(
    r"data-csa-c-(?:id|merchant-id|offer-id|session-id)|data-a-state|k-.*|data-components|data-atc-click-urls"
    r"|data-price-totals|data-a-dynamic-image|src|srcset|value|action|data-ad-.*|data-a-modal|.*pixelurl|data-adfeedbackdetails"
)
#: Classes with request IDs
DROP_CLASSES = re.compile(r"(?:pd_rd_\w+|pf_rd_\w+|content-id)-.*")


def replace_text(soup: BeautifulSoup, text: str, replacement: str) -> None:
    """Replace ``text`` in all texts and attribute values of ``soup``."""
    for node in soup.find_all(string=lambda s: text in s):
        node.replace_with(str(node).replace(text, replacement))
    for tag in soup.find_all(True):
        for name, value in tag.attrs.items():
            if isinstance(value, str) and text in value:
                tag[name] = value.replace(text, replacement)


def hide_titles(part: Tag, titles: dict[str, str]) -> None:
    """Replace the titles and descriptions of other products in ``part``, which tell what was subscribed.

    Texts with a price or the "This item" label of a comparison widget are kept, the parser reads them.
    """

    def hidden(text: str) -> str | None:
        if len(text.strip()) < MIN_TITLE_LENGTH or PRICE_LIKE_RE.search(text) or THIS_ITEM_LABEL in text:
            return None
        return titles.setdefault(text.strip(), f"Other product {len(titles) + 1:02}")

    for node in part.find_all(string=True):
        if not isinstance(node, Comment) and (replacement := hidden(str(node))):
            node.replace_with(replacement)
    for tag in [part, *part.find_all(True)]:
        for name in ("title", "aria-label", "alt"):
            if isinstance(tag.get(name), str) and (replacement := hidden(str(tag[name]))):
                tag[name] = replacement


def shell(body: BeautifulSoup, tag: Tag, *children: Tag) -> Tag:
    """An empty copy of ``tag`` with only its id, class and style, holding ``children``."""
    shell = body.new_tag(tag.name, attrs={k: v for k, v in tag.attrs.items() if k in ("id", "class", "style")})
    for child in children:
        shell.append(child)
    return shell


def append(parent: Tag, part: Tag | None) -> None:
    """Append ``part`` to ``parent`` without scripts, images, comments, IDs and tracking parameters."""
    if part is None:
        return
    for tag in part.find_all(["style", "script", "noscript", "img", "input", "svg"]):
        tag.decompose()
    for comment in part.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in [part, *part.find_all(True)]:
        _clean_attributes(tag)
    parent.append(part)


def _clean_attributes(tag: Tag) -> None:
    for name in [n for n in tag.attrs if DROP_ATTRIBUTES.fullmatch(n)]:
        del tag[name]
    if isinstance(tag.get("class"), list):
        tag["class"] = [c for c in tag["class"] if not DROP_CLASSES.fullmatch(c)]
    if tag.get("href"):
        # Paths keep the ASIN of a link, queries only hold tracking IDs and the seller ID
        href = str(tag["href"])
        seller_id = SELLER_ID_RE.search(href)
        query = f"?seller={seller_id.group(0)}" if seller_id else ""
        tag["href"] = re.sub(r"/ref=[^/?]*|\?.*", "", href) + query
