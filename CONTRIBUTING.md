# Contributing

## Pages of another Amazon site

amazon-subscriptions reads the English Subscribe & Save pages of every Amazon site that offers English, but only
amazon.de has been tested. The texts, the markup or the URLs of another site may differ. To find out, and to keep it
working, anonymized pages of that site are needed as test fixtures. This guide shows how to capture and anonymize them
step by step. You need a Subscribe & Save account on that site, and no knowledge of the code.

> [!WARNING]
> The raw pages you capture contain your name, your address, your subscriptions, order numbers, IDs and session
> tokens. Never share them, attach them or commit them unchanged. Only share the anonymized pages, after checking
> them yourself (step 5), and delete the raw pages when you are done (step 8).

The examples use `amazon.co.uk`. Replace it with your site, and `co.uk` with the part after `amazon.`, e.g. `com`,
`ca` or `com.au`.

### 1. Install

You need [git](https://git-scm.com/) and [uv](https://docs.astral.sh/uv/getting-started/installation/), which
installs Python itself if needed.

```sh
git clone https://github.com/udondan/amazon-subscriptions
cd amazon-subscriptions
uv sync
```

All commands below are run in this directory.

### 2. Log in

```sh
uv run amazon-subscriptions --domain amazon.co.uk login
```

This asks for your e-mail address, your password and, if enabled, a one-time password. They are sent to Amazon only
and never stored. Only the session cookies are kept, in `~/.config/amazonorders/cookies.amazon.co.uk.json`, so the
next commands do not need to log in. If you already have a session for this site, `login` signs out of it first.

Check that it worked:

```sh
uv run amazon-subscriptions --domain amazon.co.uk check-session
```

### 3. Capture the pages

```sh
uv run amazon-subscriptions --domain amazon.co.uk --debug --output-dir raw list --with-prices
```

This only reads pages, it never changes a subscription. It writes every page it loads into the new directory `raw`:
the Subscribe & Save overview, its further pages, one page per upcoming delivery and the product page of each
subscription. Together, these are all pages that `list` and `upcoming` read, so you do not need to run `upcoming` as
well. The requests are logged to the terminal.

If the command fails or prints warnings, keep its output: it tells what is not understood yet (step 7). If it ends
with an error before writing any page, open an issue with the error message instead.

Always capture into a new, empty directory. If you capture again, delete `raw` first (`rm -rf raw`).

### 4. Anonymize the pages

```sh
uv run python scripts/anonymize_fixtures.py --from-debug-dir raw --output-dir tests/fixtures/co.uk \
    --replace "Jane Doe=Test Person" --sensitive "Jane" --sensitive "Doe" --sensitive "High Street"
```

Replace `Jane Doe` with your name as Amazon shows it, and add a `--sensitive` for each part of your name and address
that must not appear in the result. Each option can be given several times.

The script sorts the pages by their content and writes `landing.html`, `delivery-1.html`, `delivery-2.html` and so
on, and, if the lists have further pages, `subscriptions-page-2.html` and `deliveries-page-2.html` to
`tests/fixtures/co.uk/`. It replaces:

- product titles with `Product 01`, `Product 02` and so on (followed by filler words), also in links,
- ASINs, subscription IDs, delivery IDs and session IDs with fake values,
- addresses, tokens and the values of your session cookies,
- every text given with `--replace`.

It does not replace free text, such as your name in a greeting or a message, and nothing the page shows in an
unknown place. Prices, quantities, intervals and dates are kept.

Afterwards, it checks every page for the sensitive values it has seen. If one is left, it prints `LEAK` and exits
with status 1. It also prints a `WARN` line for text that looks like personal data: e-mail addresses, phone numbers,
order and session numbers, customer IDs, names after "Hello" or "Deliver to", postcodes and product names in links.
The value itself is masked. Look at each of them; if it is personal, add a `--replace` or `--sensitive` for it, delete
`tests/fixtures/co.uk` and run the command again.

At the end, it prints a command for the product pages, like this:

```text
    python scripts/extract_product_fixture.py --output-dir tests/fixtures/co.uk --asin-map raw/asin-map.json \
        raw/B0XXXXXXXX_0.html raw/B0YYYYYYYY_0.html …
```

Run it with `uv run` in front:

```sh
uv run python scripts/extract_product_fixture.py --output-dir tests/fixtures/co.uk --asin-map raw/asin-map.json \
    raw/B0XXXXXXXX_0.html raw/B0YYYYYYYY_0.html …
```

It reduces each product page to its title and price blocks, replaces titles, ASINs, seller names and IDs, and
writes it as `product-<fake ASIN>.html`. For each page, it prints what the parser reads from it:

```text
ok   tests/fixtures/co.uk/product-B0TEST0024.html: price 8.69, list price 11.99 (rrp, from buybox), unit price 57.93 per l
ok   tests/fixtures/co.uk/product-B0TEST0046.html: no price
```

Keep about five pages that show different things, e.g. a recommended retail price (`rrp`), a former price (`was`),
a product without price (not available), one with an alternative offer, and one with a plain price. Delete the
others. You may rename the ones you keep to say what they show, e.g. `product-rrp.html`.

### 5. Check the pages yourself

The scripts only replace what they know about. Search the anonymized pages for your own data, with every value you
can think of: your first and last name, street, postcode, town, e-mail address and phone number.

```sh
grep -rniE "jane|doe|high street|SW1A 1AA|jane@example.com|7700 900123" tests/fixtures/co.uk/
```

Search for order numbers too; `000-0000000-0000000` is the placeholder of the scripts. This must find nothing:

```sh
grep -rnoE "[0-9]{3}-[0-9]{7}-[0-9]{7}" tests/fixtures/co.uk/ | grep -v 000-0000000-0000000
```

Then run the scan of step 4 once more on all pages, including the product pages:

```sh
uv run python scripts/privacy_scan.py tests/fixtures/co.uk/*.html
```

It ends with "Nothing found" or lists `WARN` lines as in step 4. If something personal is left, add a `--replace` or
`--sensitive` for it in step 4, delete `tests/fixtures/co.uk` and run steps 4 and 5 again. For a product page, you
can also delete it.

### 6. Share the pages

Either way, describe in a few words what your subscriptions look like (e.g. "one paused subscription, one with a
backup product") and include the output and warnings of step 3, after checking them for personal data as well.

- **Pull request**: [Fork the repository](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/fork-a-repo),
  commit only the directory `tests/fixtures/co.uk/` and open a pull request. Its title follows
  [Conventional Commits](https://www.conventionalcommits.org/), e.g. `test: add pages of amazon.co.uk`.
- **Issue**: If you do not want to open a pull request, pack the directory (`zip -r co.uk.zip tests/fixtures/co.uk`)
  and attach the archive to a [new issue](https://github.com/udondan/amazon-subscriptions/issues/new).

### 7. Unknown texts, formats and markup

If step 3 printed warnings or the result misses values, the site shows something that is not known yet. You do not
need to fix it yourself; the pages from step 6 are enough to do it. If you want to, this is where it goes:

- **Texts** (e.g. "Next delivery:", "Arriving", "RRP", status and alert texts) and **date and amount formats**:
  `amazon_subscriptions/locales/en.py`. The `TODO` comments there name the texts that are not known yet for any site.
  Only take texts from real pages, never guess them.
- **Currency**: `SITE_CURRENCIES` in `amazon_subscriptions/locales/__init__.py`.
- **Markup**: the CSS selectors in `amazon_subscriptions/parse/selectors.py`.
- **URLs**: the allow-list in `amazon_subscriptions/client.py`. Only add pages that are read; never add a URL that
  changes a subscription.

Add tests in `tests/` that read your fixtures, and run them with:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

(With [mise](https://mise.jdx.dev/), `mise run lint` and `mise run test` do the same.)

### 8. Clean up

Delete the raw pages, and the pages that could not be read, if any were saved:

```sh
rm -rf raw ~/.cache/amazon-subscriptions/failed
```

To end the session as well:

```sh
uv run amazon-subscriptions --domain amazon.co.uk logout
```
