from bs4 import BeautifulSoup, Tag

from amazon_subscriptions.exceptions import CaptchaError, SessionExpiredError
from amazon_subscriptions.locales.base import normalize_space
from amazon_subscriptions.parse import selectors


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def text_of(tag: Tag | None, separator: str = " ") -> str | None:
    """The normalized text of a tag, or ``None`` if the tag is missing or empty."""
    if tag is None:
        return None
    return normalize_space(tag.get_text(separator)) or None


def attr_of(tag: Tag | None, name: str) -> str | None:
    value = tag.get(name) if tag is not None else None
    if isinstance(value, list):
        value = " ".join(value)
    return value or None


def check_page(soup: BeautifulSoup, page: str | None = None) -> None:
    """Raise if the page is a captcha or sign-in page instead of the requested one."""
    if any(soup.select_one(selector) for selector in selectors.CAPTCHA):
        raise CaptchaError(
            "Amazon answered with a captcha. Open Amazon in a browser, solve it there and try again later."
            + (f" (page: {page})" if page else "")
        )
    if any(soup.select_one(selector) for selector in selectors.SIGN_IN):
        raise SessionExpiredError("The Amazon session has expired" + (f" (page: {page})" if page else "") + ".")
