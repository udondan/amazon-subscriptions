# amazon-subscriptions

Read Amazon Subscribe & Save subscriptions and upcoming deliveries as JSON. Strictly read-only.

Built on [amazon-orders](https://github.com/udondan/amazon-orders), which handles login and the session. Supported
so far: amazon.de.

## Installation

```sh
uv tool install git+https://github.com/udondan/amazon-subscriptions
```

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
`~/.config/amazonorders/cookies.json` and shared with amazon-orders.

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
        "asin": "B0TEST0001"
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
when scrolling) and the page of each upcoming delivery. Every URL is checked against an allow-list before it is
requested, so links that change subscriptions (skip, pause, cancel, change quantity or interval, deliver now) are
never requested.

## Development

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

The test fixtures in `tests/fixtures` are anonymized pages of amazon.de, see `scripts/anonymize_fixtures.py`.
