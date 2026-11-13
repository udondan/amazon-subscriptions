"""The text output of the ``amazon-subscriptions`` command, one line per subscription or delivery item."""

from typing import Any

from amazon_subscriptions.models import Interval, Subscription, UpcomingDelivery


def next_delivery_key(subscription: Subscription) -> tuple[bool, str, str]:
    """Sort subscriptions by next delivery and title, those without next delivery last."""
    date = subscription.next_delivery_date
    return date is None, date.isoformat() if date else "", subscription.title or ""


def _format_interval(interval: Interval | None) -> str:
    if interval is None:
        return "?"
    return f"every {interval.every} {interval.unit.value}{'s' if interval.every != 1 else ''}"


def _format_amount(amount: Any, currency: str | None) -> str:
    return f"{amount} {currency or ''}".strip() if amount is not None else "-"


def _format_prices(s: Subscription) -> str:
    """The prices of the product page, loaded with ``--with-prices``."""
    if s.price is None:
        return ""
    unit = f", {_format_amount(s.unit_price, s.currency)}/{s.unit_price_unit}" if s.unit_price is not None else ""
    list_price = ""
    if s.list_price is not None and s.list_price_type is not None:
        list_price = f", {s.list_price_type.value} {_format_amount(s.list_price, s.currency)}"
    alternative = ""
    if s.alternative_offer is not None:
        seller = f" from {s.alternative_offer.seller}" if s.alternative_offer.seller else ""
        alternative = f", alternative offer {_format_amount(s.alternative_offer.price, s.currency)}{seller}"
    return f"  (regular {_format_amount(s.price, s.currency)}{unit}{list_price}{alternative})"


def format_subscription(s: Subscription) -> str:
    date = s.next_delivery_date.isoformat() if s.next_delivery_date else "?"
    price = f"  {_format_amount(s.subscription_price, s.currency)}" if s.subscription_price is not None else ""
    price += _format_prices(s)
    status = f"  [{s.status.value}]" if s.status.value not in ("active", "unknown") else ""
    status += "  [incomplete]" if s.parse_errors else ""
    return f"{date}  {s.quantity or '?'} x {s.title or s.asin}  ({_format_interval(s.interval)}){price}{status}"


def format_delivery(d: UpcomingDelivery) -> str:
    deadline = f", changes until {d.change_deadline.isoformat()}" if d.change_deadline else ""
    incomplete = "  [incomplete]" if d.parse_errors else ""
    total = _format_amount(d.total, d.currency)
    lines = [f"{d.date.isoformat()}: {len(d.items)} items, total {total}{deadline}{incomplete}"]
    for item in d.items:
        discount = f" (-{item.discount_percent}%)" if item.discount_percent is not None else ""
        substitute = ""
        if item.substitute:
            substitute = f"  [backup product {item.substitute_asin}]" if item.substitute_asin else "  [backup product]"
        price = _format_amount(item.price, d.currency)
        lines.append(f"  {item.quantity or '?'} x {item.title}  {price}{discount}{substitute}")
    return "\n".join(lines)
