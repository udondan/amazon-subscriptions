"""The ``amazon-subscriptions`` command.

``login``, ``logout`` and ``check-session`` are the commands of amazon-orders, so the session is shared with it.
"""

import logging
from typing import Any

import click
from amazonorders.cli import IOClick, check_session, login, logout
from amazonorders.conf import AmazonOrdersConfig
from amazonorders.exception import AmazonOrdersError
from amazonorders.session import AmazonSession

from amazon_subscriptions.client import SubscriptionsClient
from amazon_subscriptions.exceptions import SessionExpiredError, SubscriptionsError
from amazon_subscriptions.models import Interval, Subscription, UpcomingDelivery
from amazon_subscriptions.serialize import to_json


class _Group(click.Group):
    """Show errors of both packages as messages instead of tracebacks."""

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except SessionExpiredError as e:
            domain = f" --domain {ctx.params['domain']}" if ctx.params.get("domain") else ""
            raise click.ClickException(
                f"{e} Sign in again with:\n  amazon-subscriptions{domain} logout\n  amazon-subscriptions{domain} login"
            ) from e
        except (SubscriptionsError, AmazonOrdersError) as e:
            logging.getLogger(__name__).debug("An error occurred.", exc_info=True)
            raise click.ClickException(str(e)) from e


@click.group(cls=_Group)
@click.option(
    "--domain",
    help="The Amazon domain, e.g. amazon.de. Defaults to the domain configured for amazon-orders.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Log the requests to stderr and write every page to the output directory.",
)
@click.option("--output-dir", help="The directory for the pages written with --debug.")
@click.pass_context
def cli(ctx: click.Context, domain: str | None, debug: bool, output_dir: str | None) -> None:
    """Read Amazon Subscribe & Save subscriptions and upcoming deliveries. Strictly read-only."""
    if debug:
        handler = logging.StreamHandler()
        for name in ("amazon_subscriptions", "amazonorders"):
            logging.getLogger(name).setLevel(logging.DEBUG)
            logging.getLogger(name).addHandler(handler)

    data: dict[str, Any] = {}
    if domain:
        data["domain"] = domain
    if output_dir:
        data["output_dir"] = output_dir
    conf = AmazonOrdersConfig(data=data)
    ctx.ensure_object(dict)
    # The keys the commands of amazon-orders expect
    ctx.obj["conf"] = conf
    ctx.obj["amazon_session"] = AmazonSession(debug=debug, io=IOClick(), config=conf)


cli.add_command(login)
cli.add_command(logout)
cli.add_command(check_session)


def _client(ctx: click.Context) -> SubscriptionsClient:
    return SubscriptionsClient(ctx.obj["amazon_session"])


@cli.command("list")
@click.option("--json", "as_json", is_flag=True, default=False, help="Print JSON.")
@click.pass_context
def list_subscriptions(ctx: click.Context, as_json: bool) -> None:
    """List all subscriptions."""
    subscriptions = _client(ctx).get_subscriptions()
    if as_json:
        click.echo(to_json(subscriptions))
        return
    for subscription in sorted(subscriptions, key=_next_delivery_key):
        click.echo(_format_subscription(subscription))
    click.echo(f"\n{len(subscriptions)} subscriptions")


@cli.command()
@click.option("--json", "as_json", is_flag=True, default=False, help="Print JSON.")
@click.pass_context
def upcoming(ctx: click.Context, as_json: bool) -> None:
    """List the upcoming deliveries with their items."""
    deliveries = _client(ctx).get_upcoming_deliveries()
    if as_json:
        click.echo(to_json(deliveries))
        return
    for index, delivery in enumerate(deliveries):
        if index:
            click.echo()
        click.echo(_format_delivery(delivery))


def _next_delivery_key(subscription: Subscription) -> tuple[bool, str, str]:
    date = subscription.next_delivery_date
    return date is None, date.isoformat() if date else "", subscription.title or ""


def _format_interval(interval: Interval | None) -> str:
    if interval is None:
        return "?"
    return f"every {interval.every} {interval.unit.value}{'s' if interval.every != 1 else ''}"


def _format_amount(amount: Any, currency: str | None) -> str:
    return f"{amount} {currency or ''}".strip() if amount is not None else "-"


def _format_subscription(s: Subscription) -> str:
    date = s.next_delivery_date.isoformat() if s.next_delivery_date else "?"
    price = f"  {_format_amount(s.subscription_price, s.currency)}" if s.subscription_price is not None else ""
    status = f"  [{s.status.value}]" if s.status.value not in ("active", "unknown") else ""
    return f"{date}  {s.quantity or '?'} x {s.title or s.asin}  ({_format_interval(s.interval)}){price}{status}"


def _format_delivery(d: UpcomingDelivery) -> str:
    deadline = f", changes until {d.change_deadline.isoformat()}" if d.change_deadline else ""
    lines = [f"{d.date.isoformat()}: {len(d.items)} items, total {_format_amount(d.total, d.currency)}{deadline}"]
    for item in d.items:
        discount = f" (-{item.discount_percent}%)" if item.discount_percent is not None else ""
        substitute = ""
        if item.substitute:
            substitute = f"  [backup product {item.substitute_asin}]" if item.substitute_asin else "  [backup product]"
        price = _format_amount(item.price, d.currency)
        lines.append(f"  {item.quantity or '?'} x {item.title}  {price}{discount}{substitute}")
    return "\n".join(lines)
