# amazon-subscriptions

Read Amazon Subscribe & Save subscriptions and upcoming deliveries as JSON. Strictly read-only.

Built on [amazon-orders](https://github.com/alexdlaird/amazon-orders), which handles login and the session, and
requests every page in English, whatever language the account is set to. Every Amazon site that offers its pages in
English is supported; so far it is tested with amazon.de. See [Other sites](#other-sites).

## Installation

Requires Python 3.10 or later. Install the CLI from [PyPI](https://pypi.org/project/amazon-subscriptions/) with
[uv](https://docs.astral.sh/uv/):

```sh
uv tool install amazon-subscriptions
```

Or with [pipx](https://pipx.pypa.io/):

```sh
pipx install amazon-subscriptions
```

To use it as a [library](#library), add it to your project:

```sh
uv add amazon-subscriptions  # or: pip install amazon-subscriptions
```

Or from a checkout, prefixing the commands below with `uv run`:

```sh
uv sync
```

The installation includes amazon-orders; its CLI is not needed.

## Usage

```sh
amazon-subscriptions login              # asks for username, password and one-time password
amazon-subscriptions list               # all subscriptions
amazon-subscriptions upcoming           # upcoming deliveries with their items
amazon-subscriptions list --json
amazon-subscriptions list --with-prices # also regular, list, unit and alternative prices from the product pages
amazon-subscriptions upcoming --json
amazon-subscriptions check-session
amazon-subscriptions logout
```

`login`, `logout` and `check-session` are the commands of amazon-orders. Each Amazon site has its own session, stored
in `~/.config/amazonorders/cookies.<site>.json` (e.g. `cookies.amazon.de.json`, for amazon.com `cookies.json`) and
shared with amazon-orders. A session that older versions of amazon-orders stored in `cookies.json` for another site is
still used. Credentials are only asked for by `login` and never stored; the other commands never log in by themselves.
`login` signs out of the site's stored session first, so it always starts a new one. `login --browser` signs in
through a browser window instead, which needs the `browser` extra of amazon-orders. `check-session --verify` asks
Amazon whether it still accepts the session.

A `language_package` configured for amazon-orders is ignored, as the pages are only read in English. The configuration
file is not changed.

Both `list` and `upcoming` load the same pages, about 3 requests plus one per upcoming delivery: `list` needs the
delivery pages for the prices of the next delivery. `list --with-prices` loads the product page of every subscription
on top, one request each.

Options (before the command):

| Option | Description |
| --- | --- |
| `--domain amazon.de` | The Amazon domain. Defaults to `domain` in `~/.config/amazonorders/config.yml`. |
| `--debug` | Log the requests to stderr and write every loaded page to the output directory. |
| `--output-dir DIR` | The directory for the pages written with `--debug`, defaults to `./output`. |

### Errors

| Exit status | Meaning |
| --- | --- |
| 0 | Complete result. |
| 1 | No result, only a message. |
| 2 | Partial result: some delivery or product pages could not be read. The output is complete JSON (or text), the affected entries have `parse_errors` (text output: `[incomplete]`), and each error is printed to stderr. |

The command exits with status 1 if

- there is no session or it has expired. Run `amazon-subscriptions logout` and `amazon-subscriptions login` (with the
  same `--domain`, if any),
- the overview (`/auto-deliveries` and its further pages) cannot be loaded, e.g. because Amazon answers with a
  captcha (open Amazon in a browser, solve it there and try again later) or has changed the page. The message names
  the page; run again with `--debug` to keep it. An empty result is only returned if Amazon says so.

A delivery or product page that cannot be loaded or read is loaded once more after 2 seconds, as Amazon sometimes
serves another variant of a page. If it fails again, the result is partial (status 2):

- A delivery without date is dated by the `deliveryDate` of its URL, and keeps its items.
- A delivery page without items gives the delivery as its card on the overview shows it: date, change deadline and
  number of items, but `items` is empty and `total` is `null`. The subscriptions of that delivery get its error too,
  as their `discount_percent` and `subscription_price` may be missing.
- A product page leaves the prices of its subscription `null`.
- A captcha is not retried. It stops loading the remaining delivery and product pages, which then fail too.

Every received page that could not be read is saved to `~/.cache/amazon-subscriptions/failed/` (or
`$XDG_CACHE_HOME/amazon-subscriptions/failed/`), also without `--debug`, as `<timestamp>_<page>_<attempt>.html`. The
path is printed to stderr and is in `html_path` of the error:

```text
Error: No delivery date found, it was taken from the URL (page: https://www.amazon.de/auto-deliveries/?…), page saved to ~/.cache/amazon-subscriptions/failed/20261021-220012_delivery-2026-11-01_2.html
```

The pages written with `--debug` and to the failed pages directory contain your subscriptions, addresses and more.
Keep them private.

## JSON

- Dates are ISO 8601 (`2026-11-01`).
- Amounts are decimal strings (`"12.34"`), in the currency of the ISO 4217 code in `currency`.
- Values Amazon does not show are `null`.
- Every subscription and delivery has `parse_errors`, the pages of it that could not be read (see
  [Errors](#errors)). It is empty (`[]`) if the entry is complete:

```json
{
  "url": "https://www.amazon.de/auto-deliveries/?…&deliveryDate=1793487600000&…",
  "message": "No delivery date found, it was taken from the URL",
  "selector": "[data-testid='ddp-atd-delivery-date']",
  "html_path": "/Users/…/.cache/amazon-subscriptions/failed/20261021-220012_delivery-2026-11-01_2.html"
}
```

| Field | Description |
| --- | --- |
| `url` | The page that could not be read. |
| `message` | What went wrong, e.g. a missing element, an HTTP status or a captcha. |
| `selector` | CSS selector of the missing element, `null` if the page was not read at all. |
| `html_path` | Where the page was saved, `null` if no page was received (e.g. an HTTP error). |

### `list --json`

A list of subscriptions:

```json
[
  {
    "subscription_id": "…",
    "asin": "B0TEST0001",
    "title": "Product 01",
    "product_url": "https://www.amazon.de/dp/B0TEST0001",
    "image_url": "https://m.media-amazon.com/images/I/….jpg",
    "quantity": 1,
    "interval": {"every": 2, "unit": "month"},
    "next_delivery_date": "2026-11-01",
    "status": "active",
    "price": "8.69",
    "list_price": "11.99",
    "list_price_type": "rrp",
    "list_price_source": "buybox",
    "discount_percent": 15,
    "subscription_price": "7.39",
    "unit_price": "57.93",
    "unit_price_unit": "l",
    "alternative_offer": null,
    "currency": "EUR",
    "raw_status_text": null,
    "parse_errors": []
  }
]
```

| Field | Description |
| --- | --- |
| `interval.unit` | `day`, `week` or `month`. |
| `status` | `active`, `paused`, `unavailable` (a backup product is sent instead), `skipped` or `unknown`. |
| `discount_percent`, `subscription_price` | Discount and price of the whole quantity in the next delivery. Only set if that delivery shows prices, usually only the next one. |
| `price`, `list_price` | Regular (one-time purchase) price of one unit in the buybox of the product page, and the strike-through price shown for it. Only read with `--with-prices`, `null` if the product is not available or the page shows no list price. Prices of other variants, sponsored products and recommendations on the page are never used. |
| `list_price_type` | What `list_price` is, by its label: `rrp` (recommended retail price, "RRP"), `lowest_30d` (lowest price in the last 30 days, see [Limitations](#limitations)) or `was` (previous price, "Was"). `null` without `list_price`. |
| `list_price_source` | Where `list_price` was read: `buybox` (price block of the buybox, any type), `widget` (the entry of this product, "This item:", in a comparison widget, only `rrp`) or `alternative_offer` (price block of an alternative offer of the same product, only `rrp`). Tried in this order. |
| `unit_price`, `unit_price_unit` | Price per unit of measure of `price` and its unit as Amazon shows it, e.g. `"57.93"` and `"l"`, `"kg"` or `"count"`. Only read with `--with-prices`. |
| `alternative_offer` | The cheapest other offer of the same product next to the buybox offer ("Another way to buy"), e.g. of another seller, or `null`: `{"price": "5.45", "unit_price": "1.36", "unit_price_unit": "count", "seller": "…", "seller_id": "A1B2C3D4E5F6G7", "subscribable": false}`. `seller` is the seller name as the offer shows it, `Amazon` if Amazon sells it, or `null` if the page does not show a name. `seller_id` is the merchant ID from the link to the seller profile, `null` if Amazon sells the offer or the page has no such link. These offers cannot be subscribed to, so `subscribable` is always `false`. Only read with `--with-prices`. |
| `raw_status_text` | The status or alert text shown by Amazon, e.g. for a backup product. |
| `parse_errors` | The errors of the product page (`--with-prices`) and of the page of the next delivery, if they could not be read. |

### `upcoming --json`

A list of deliveries:

```json
[
  {
    "date": "2026-11-01",
    "change_deadline": "2026-10-27",
    "items": [
      {
        "title": "Product 01",
        "quantity": 1,
        "interval": {"every": 2, "unit": "month"},
        "price": "7.39",
        "discount_percent": 15,
        "alert_text": null,
        "substitute": false,
        "subscription_id": "…",
        "asin": "B0TEST0001",
        "substitute_asin": null
      }
    ],
    "discount_tier": {"item_count": 11, "max_discount_unlocked": true, "savings": "10.58"},
    "total": "86.20",
    "currency": "EUR",
    "delivery_bundle_id": "…",
    "url": "https://www.amazon.de/auto-deliveries/?…",
    "parse_errors": []
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
| `discount_tier` | `item_count` is the number of items the discount is based on, `max_discount_unlocked` whether the delivery has the highest discount ("Max savings unlocked"), `savings` the amount saved as Amazon states it ("Saving €10.58"), usually only for the next delivery, otherwise `null`. |
| `total` | Sum of the item prices, `null` if an item has no price. |
| `parse_errors` | The errors of the delivery page, if it could not be read. `items` is then empty if the page had no items. |

## Library

```python
from amazonorders.conf import AmazonOrdersConfig
from amazonorders.session import AmazonSession

from amazon_subscriptions.client import SubscriptionsClient
from amazon_subscriptions.serialize import to_json

session = AmazonSession(config=AmazonOrdersConfig())  # logged in with `amazon-subscriptions login`
client = SubscriptionsClient(session)  # with_prices=True also loads the product pages
print(to_json(client.get_subscriptions()))
print(to_json(client.get_upcoming_deliveries()))
if client.errors:  # the result is partial, see parse_errors
    print(to_json(client.errors))
```

`SubscriptionsClient` also takes `retry_delay` (seconds before loading a failed page again, default 2) and
`failed_dir` (where failed pages are saved, default `~/.cache/amazon-subscriptions/failed`).

The parsers in `amazon_subscriptions.parse` are pure functions of the page HTML and send no requests.

## Read-only

The client only requests the Subscribe & Save overview, the further pages of its lists (loaded like the browser does
when scrolling), the page of each upcoming delivery and, if a backup product is sent instead of a subscribed one, the
detail sheet of that subscription. With `--with-prices` (`with_prices=True`) it also requests the product page
(`/dp/<ASIN>`) of each subscription. Every URL is checked against an allow-list before it is requested, so links that
change subscriptions (skip, pause, cancel, change quantity or interval, deliver now) are never requested.

## Limitations

- Prices are only known for deliveries that show them, which is usually only the next one. `subscription_price` and
  `discount_percent` of a subscription are therefore only set if its next delivery is that one.
- Regular, list and unit prices are not shown on the Subscribe & Save pages. They are only read with `--with-prices`,
  from the product pages of the subscribed products, so a backup product sent instead has none. Loading 30 or more
  product pages at once can make Amazon answer with a captcha; the remaining prices then stay `null` with a warning.
- Some English texts are not known yet, as no page with them has been captured. Until they are added to
  `amazon_subscriptions/locales/en.py`:
  - paused, skipped and unavailable subscriptions on the overview give `unknown` and a warning;
  - `list_price_type` is never `lowest_30d`, as that label is not known. amazon.de no longer showed the lowest price
    of the last 30 days on any product page checked, in German either.

  Please contribute such pages, see [CONTRIBUTING.md](CONTRIBUTING.md).
- Only the deliveries shown on the overview and its further pages are read, which Amazon limits to a few months.

## Other sites

All Amazon sites that offer their pages in English use the same English locale: dates are read as `1 Oct` and as
`Oct 1`, amounts as `12.34` and `1,234.56`, and the currency is the ISO 4217 code of the site (the pages only show its
symbol, and `$` alone does not tell US, Canadian and Australian dollars apart). Sites without English pages, such as
amazon.com.br, amazon.com.mx, amazon.com.tr and amazon.pl, are refused.

Only amazon.de has been tested so far. On other sites, the texts, the markup of the pages or the URLs may differ, so
some values may be missing (with a warning or an `[incomplete]` result) or a page may not be read at all. Login,
session and cookies are handled by amazon-orders for all sites.

If you use another site, please contribute anonymized pages of it, so it can be tested.
[CONTRIBUTING.md](CONTRIBUTING.md) explains step by step how to capture and anonymize them.

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

The test fixtures in `tests/fixtures/<tld>/` are anonymized English pages, see [CONTRIBUTING.md](CONTRIBUTING.md) for
how to capture and anonymize them. The product page fixtures (`product*.html`) are reduced to their title and price
blocks with `scripts/extract_product_fixture.py`. It also keeps the variants, the comparison widget and a sponsored
product, as prices the parser must not read.
