# amazon-subscriptions

Read Amazon Subscribe & Save subscriptions and upcoming deliveries as JSON. Strictly read-only.

Built on [amazon-orders](https://github.com/udondan/amazon-orders), which handles login and the session. Supported
so far: amazon.de.

## Installation

Requires Python 3.10 or later. With [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/udondan/amazon-subscriptions
```

Or from a checkout, prefixing the commands below with `uv run`:

```sh
uv sync
```

The installation includes amazon-orders; its CLI is not needed.

There is no package on PyPI yet: the amazon.de support of amazon-orders is not released yet, so it is required from a
commit of a fork, and PyPI does not accept dependencies like that.

## Usage

```sh
amazon-subscriptions login              # asks for username, password and one-time password
amazon-subscriptions list               # all subscriptions
amazon-subscriptions upcoming           # upcoming deliveries with their items
amazon-subscriptions list --json
amazon-subscriptions upcoming --json
amazon-subscriptions check-session
amazon-subscriptions logout
```

`login`, `logout` and `check-session` are the commands of amazon-orders. The session is stored in
`~/.config/amazonorders/cookies.json` and shared with amazon-orders. Credentials are only asked for by `login` and
never stored; the other commands never log in by themselves.

Both `list` and `upcoming` load the same pages, about 3 requests plus one per upcoming delivery: `list` needs the
delivery pages for the prices of the next delivery.

Options (before the command):

| Option | Description |
| --- | --- |
| `--domain amazon.de` | The Amazon domain. Defaults to `domain` in `~/.config/amazonorders/config.yml`. |
| `--debug` | Log the requests to stderr and write every loaded page to the output directory. |
| `--output-dir DIR` | The directory for the pages written with `--debug`, defaults to `./output`. |

### Errors

The command exits with status 1 and a message if

- there is no session or it has expired. Run `amazon-subscriptions logout` and `amazon-subscriptions login` (with the
  same `--domain`, if any),
- Amazon answers with a captcha. Open Amazon in a browser, solve it there and try again later,
- a page does not have the expected structure, most likely because Amazon changed it. The message names the page;
  run again with `--debug` to keep it. An empty result is only returned if Amazon says so.

The pages written with `--debug` contain your subscriptions, addresses and more. Keep them private.

## JSON

- Dates are ISO 8601 (`2026-10-01`).
- Amounts are decimal strings (`"12.34"`), in the currency of the ISO 4217 code in `currency`.
- Values Amazon does not show are `null`.

### `list --json`

A list of subscriptions:

```json
[
  {
    "subscription_id": "…",
    "asin": "B0TEST0001",
    "title": "Testartikel 01",
    "product_url": "https://www.amazon.de/dp/B0TEST0001",
    "image_url": "https://m.media-amazon.com/images/I/….jpg",
    "quantity": 1,
    "interval": {"every": 2, "unit": "month"},
    "next_delivery_date": "2026-10-01",
    "status": "active",
    "price": null,
    "list_price": null,
    "discount_percent": 15,
    "subscription_price": "12.34",
    "unit_price": null,
    "unit_price_unit": null,
    "currency": "EUR",
    "raw_status_text": null
  }
]
```

| Field | Description |
| --- | --- |
| `interval.unit` | `day`, `week` or `month`. |
| `status` | `active`, `paused`, `unavailable` (a backup product is sent instead), `skipped` or `unknown`. |
| `discount_percent`, `subscription_price` | Discount and price of the whole quantity in the next delivery. Only set if that delivery shows prices, usually only the next one. |
| `price`, `list_price`, `unit_price` | Not shown on the pages that are read, so far always `null`. |
| `raw_status_text` | The status or alert text shown by Amazon, e.g. for a backup product. |

### `upcoming --json`

A list of deliveries:

```json
[
  {
    "date": "2026-10-01",
    "change_deadline": "2026-09-26",
    "items": [
      {
        "title": "Testartikel 01",
        "quantity": 1,
        "interval": {"every": 2, "unit": "month"},
        "price": "12.34",
        "discount_percent": 15,
        "alert_text": null,
        "substitute": false,
        "subscription_id": "…",
        "asin": "B0TEST0001",
        "substitute_asin": null
      }
    ],
    "discount_tier": {"item_count": 11, "max_discount_unlocked": true, "savings": "12.34"},
    "total": "150.19",
    "currency": "EUR",
    "delivery_bundle_id": "…",
    "url": "https://www.amazon.de/auto-deliveries/?…"
  }
]
```

| Field | Description |
| --- | --- |
| `change_deadline` | The last day to change the delivery. |
| `items[].price` | Price of the whole quantity with the discount applied. Amazon shows prices only for the next delivery. |
| `items[].substitute` | `true` if a backup product is sent instead of the subscribed one; `alert_text` has Amazon's note. |
| `items[].asin`, `items[].substitute_asin` | `asin` is always the subscribed product. If `substitute` is `true`, `title`, `price` and `discount_percent` are those of the backup product, and `substitute_asin` is its ASIN. It is read from the subscription's detail sheet and is `null` if that sheet names another backup product. |
| `items[].subscription_id` | The subscription of the item. Delivery pages do not link items to subscriptions, so they are matched by title, quantity and interval; `null` if there is no unique match. |
| `total` | Sum of the item prices, `null` if an item has no price. |

## Library

```python
from amazonorders.conf import AmazonOrdersConfig
from amazonorders.session import AmazonSession

from amazon_subscriptions.client import SubscriptionsClient
from amazon_subscriptions.serialize import to_json

session = AmazonSession(config=AmazonOrdersConfig())  # logged in with `amazon-subscriptions login`
client = SubscriptionsClient(session)
print(to_json(client.get_subscriptions()))
print(to_json(client.get_upcoming_deliveries()))
```

The parsers in `amazon_subscriptions.parse` are pure functions of the page HTML and send no requests.

## Read-only

The client only requests the Subscribe & Save overview, the further pages of its lists (loaded like the browser does
when scrolling), the page of each upcoming delivery and, if a backup product is sent instead of a subscribed one, the
detail sheet of that subscription. Every URL is checked against an allow-list before it is requested, so links that
change subscriptions (skip, pause, cancel, change quantity or interval, deliver now) are never requested.

## Limitations

- Prices are only known for deliveries that show them, which is usually only the next one. `subscription_price` and
  `discount_percent` of a subscription are therefore only set if its next delivery is that one.
- Regular, list and unit prices are not shown on the pages that are read.
- The status texts of paused, skipped and unavailable subscriptions on the overview are not known yet, so they give
  `unknown` and a warning. A subscription whose next delivery sends a backup product is `unavailable`.
- Only the deliveries shown on the overview and its further pages are read, which Amazon limits to a few months.

## Other storefronts

A storefront needs a subclass of `SubscriptionLocale` in `amazon_subscriptions/locales/`, registered in
`LOCALES_BY_TLD`, and anonymized fixtures of its pages in `tests/fixtures/<tld>/`. The texts are taken from real pages;
none are guessed.

For amazon.com this means:

1. **Pages**: The overview (`/auto-deliveries`), one further page of each list (`--debug` writes them as
   `paginate-*.html`) and the upcoming delivery pages, anonymized with `scripts/anonymize_fixtures.py`.
2. **Month names**: `EnUS` of amazon-orders defines no `MONTHS` (it parses dates without a fixed format), so
   `SubscriptionLocale` refuses it. amazon-orders would need English month names, as `DeDE` has.
3. **Date order**: The date pattern of `SubscriptionLocale` expects day before month (`1. Okt.`). amazon.com writes
   month before day (`Oct 1`), so the pattern has to become part of the locale.
4. **Texts**: Everything in `DeSubscriptionLocale`: prefixes of next delivery, arrival and change deadline, quantity and
   interval (`1 unit every 2 months`?), discount, item count, savings, maximum discount, backup product alerts, tile
   links and status texts.
5. **Amounts**: `USD`, `1,234.56` with `,` as thousands separator and `$` as noise.
6. **Markup**: The selectors in `amazon_subscriptions/parse/selectors.py`, the widget paths and `page-type=RCXSubs` of
   the further pages, and the URL allow-list in `amazon_subscriptions/client.py` are those of amazon.de. They are
   probably shared by all storefronts, but must be checked against the fixtures.

Login, session and cookies of amazon.com are already handled by amazon-orders.

## Development

With [mise](https://mise.jdx.dev/), which installs Python and uv:

```sh
mise run install    # uv sync
mise run lint       # ruff, ruff format and mypy
mise run lint-fix
mise run test       # pytest
```

Pull request titles and commits follow [Conventional Commits](https://www.conventionalcommits.org/); release-please
creates the releases and the changelog from them.

The test fixtures in `tests/fixtures` are anonymized pages of amazon.de, see `scripts/anonymize_fixtures.py`.
