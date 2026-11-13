"""The ``amazon-subscriptions`` command.

``login``, ``logout`` and ``check-session`` are the commands of amazon-auth, so the session is shared with it.
"""

import logging
from typing import Any

import click
from amazonauth.cli import IOClick, check_session, login, logout
from amazonauth.conf import AmazonAuthConfig
from amazonauth.exception import AmazonAuthError
from amazonauth.session import AmazonSession

from amazon_subscriptions.client import SubscriptionsClient
from amazon_subscriptions.exceptions import SessionExpiredError, SubscriptionsError
from amazon_subscriptions.serialize import to_json
from amazon_subscriptions.text import format_delivery, format_subscription, next_delivery_key


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
        except (SubscriptionsError, AmazonAuthError) as e:
            logging.getLogger(__name__).debug("An error occurred.", exc_info=True)
            raise click.ClickException(str(e)) from e


@click.group(cls=_Group)
@click.option(
    "--domain",
    help="The Amazon domain, e.g. amazon.de. Defaults to the domain configured for amazon-auth.",
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
        for name in ("amazon_subscriptions", "amazonauth"):
            logging.getLogger(name).setLevel(logging.DEBUG)
            logging.getLogger(name).addHandler(handler)

    data: dict[str, Any] = {}
    if domain:
        data["domain"] = domain
    if output_dir:
        data["output_dir"] = output_dir
    conf = AmazonAuthConfig(data=data)
    ctx.ensure_object(dict)
    # The keys the commands of amazon-auth expect
    ctx.obj["conf"] = conf
    ctx.obj["amazon_session"] = AmazonSession(debug=debug, io=IOClick(), config=conf)


cli.add_command(login)
cli.add_command(logout)
cli.add_command(check_session)


#: Exit status if some pages could not be read, so the result is incomplete.
EXIT_PARTIAL = 2


def _client(ctx: click.Context, with_prices: bool = False) -> SubscriptionsClient:
    return SubscriptionsClient(ctx.obj["amazon_session"], with_prices=with_prices)


def _exit_on_errors(ctx: click.Context, client: SubscriptionsClient) -> None:
    """Print the errors of the pages that could not be read and exit with :data:`EXIT_PARTIAL` if there are any."""
    if not client.errors:
        return
    for error in client.errors:
        saved = f", page saved to {error.html_path}" if error.html_path else ""
        click.echo(f"Error: {error.message} (page: {error.url}){saved}", err=True)
    click.echo("The result is incomplete, see parse_errors.", err=True)
    ctx.exit(EXIT_PARTIAL)


@cli.command("list")
@click.option("--json", "as_json", is_flag=True, default=False, help="Print JSON.")
@click.option(
    "--with-prices",
    is_flag=True,
    default=False,
    help="Also load each product page for the regular, list, unit and alternative offer prices (one request each).",
)
@click.pass_context
def list_subscriptions(ctx: click.Context, as_json: bool, with_prices: bool) -> None:
    """List all subscriptions."""
    client = _client(ctx, with_prices)
    subscriptions = client.get_subscriptions()
    if as_json:
        click.echo(to_json(subscriptions))
    else:
        for subscription in sorted(subscriptions, key=next_delivery_key):
            click.echo(format_subscription(subscription))
        click.echo(f"\n{len(subscriptions)} subscriptions")
    _exit_on_errors(ctx, client)


@cli.command()
@click.option("--json", "as_json", is_flag=True, default=False, help="Print JSON.")
@click.pass_context
def upcoming(ctx: click.Context, as_json: bool) -> None:
    """List the upcoming deliveries with their items."""
    client = _client(ctx)
    deliveries = client.get_upcoming_deliveries()
    if as_json:
        click.echo(to_json(deliveries))
    else:
        for index, delivery in enumerate(deliveries):
            if index:
                click.echo()
            click.echo(format_delivery(delivery))
    _exit_on_errors(ctx, client)
