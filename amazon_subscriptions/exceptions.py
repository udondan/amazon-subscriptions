class SubscriptionsError(Exception):
    """Base class of all errors of amazon-subscriptions."""


class SessionExpiredError(SubscriptionsError):
    """The session is not signed in (anymore)."""


class CaptchaError(SubscriptionsError):
    """Amazon answered with a captcha or robot check instead of the requested page."""


class PageStructureError(SubscriptionsError):
    """A page does not have the expected structure, most likely because Amazon changed it."""

    def __init__(self, message: str, page: str | None = None, selector: str | None = None) -> None:
        super().__init__(f"{message} (page: {page})" if page else message)
        self.message = message
        self.page = page
        #: CSS selector of the element that was not found, if any.
        self.selector = selector
