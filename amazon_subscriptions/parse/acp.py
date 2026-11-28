"""Parse the widgets of the landing page that load further pages by XHR (Amazon's "ACP" widgets)."""

import json
from dataclasses import dataclass

from amazon_subscriptions.exceptions import PageStructureError
from amazon_subscriptions.parse.util import Html, attr_of, soup_of


@dataclass(frozen=True)
class AcpWidget:
    """What the browser sends to load the next page of a widget, see ``SubscriptionsClient._paginate``."""

    #: Path of the widget, e.g. ``/acp/myd-hub-subscriptions-card-desktop/<id>/``.
    path: str
    #: Value of the ``x-amz-acp-params`` header.
    params: str
    stamp: str
    #: Tracking parameters of the widget (``pf_rd_p``, ``pf_rd_r``).
    tracking: dict[str, str]


def parse_acp_widget(html: Html, next_page_selector: str, page: str | None = None) -> AcpWidget | None:
    """The widget around the next page marker ``next_page_selector``, or ``None`` if there is no next page.

    :raises PageStructureError: If the marker is not inside a widget with the expected attributes.
    """
    marker = soup_of(html).select_one(next_page_selector)
    if marker is None:
        return None
    widget = marker.find_parent(attrs={"data-acp-path": True})
    path = attr_of(widget, "data-acp-path")
    params = attr_of(widget, "data-acp-params")
    stamp = attr_of(widget, "data-acp-stamp")
    try:
        tracking = json.loads(attr_of(widget, "data-acp-tracking") or "{}")
    except ValueError:
        tracking = None
    if not (path and params and stamp and isinstance(tracking, dict)):
        raise PageStructureError(f"Next page {next_page_selector!r} is not inside a widget", page)
    return AcpWidget(path, params, stamp, {k: v for k, v in tracking.items() if k in ("pf_rd_p", "pf_rd_r")})
