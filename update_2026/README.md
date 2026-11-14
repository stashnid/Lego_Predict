# Data update to 2026 (promoklocki.pl + BrickLink)

Forked from [BartekPodgorski/Lego_Predict](https://github.com/BartekPodgorski/Lego_Predict)
(data collection by Bartosz Podgórski and Wiktoria Szczepańska). Everything in this folder
is our addition; the original files in the repository root are not modified.

## What is collected — real data only

| Script | Source | What it saves |
|---|---|---|
| `promoklocki_update.py` | promoklocki.pl price-history table (PLN) | lowest offer for a new set per month (until Oct 2025) and per week (from Nov 2025), up to the day you run it, plus the catalog price |
| `bricklink_prices.py` | BrickLink API price guide | average price of **actual sales** of new sets in Europe in the last 6 months (EUR, incl. VAT) |
| `merge_2026.py` | the two files above + original Brickset table | one row per set, `lego_2026_merged.csv` |

Rules the scripts follow:
- nothing is interpolated, estimated or generated; a missing value stays empty;
- a period with no offers is not saved — the original scripts saved such days as price 0;
- the original took the monthly **maximum** of the daily lows; we keep the site's own number, the **lowest** offer of the
  month/week (weeks are combined into months by taking their minimum, so the definition stays the same);
- every line has the time it was downloaded (`scraped_at_utc`, `fetched_at_utc`), so it is visible that the data are current;
- the old `PL_retailPrice` is used only when it is a plain number: in ~2.9k rows the original scraper took
  a wrong table cell (another set's price). The new scraper looks for the retail price by its label.

## What the promoklocki price means (checked on the site, Nov 2026)

- "Najniższa cena" = the **lowest asking price of a new set** among the shops the site tracks: LEGO.com, Allegro,
  Empik Marketplace, Klockowo, brixani, also foreign shops (e.g. Rozetka). It is the price you could **buy** at,
  not a price anyone paid. For retired sets it comes from resellers (marketplaces), not from LEGO.com.
- The site states that Amazon prices and offers that need a discount code are not included in the history.
- "Cena katalogowa" = LEGO's official Polish price; it does not change after retirement.
- Until Oct 2025 the table has one row per month, from Nov 2025 one row per week.

## How to run (on your own computer)

```bash
cd update_2026
pip install -r requirements.txt

# 1) promoklocki: TEST FIRST, then the full run
python promoklocki_update.py --limit 10 --verbose
python promoklocki_update.py --only-retired --min-year 2014     # ~3.3k pages, ~3 h

# 2) BrickLink: set your keys (see the docstring of bricklink_prices.py), test, then run
export BL_CONSUMER_KEY=...  BL_CONSUMER_SECRET=...  BL_TOKEN=...  BL_TOKEN_SECRET=...
python bricklink_prices.py --limit 10 --verbose
python bricklink_prices.py --only-retired --min-year 2014

# 3) join everything
python merge_2026.py
```

On Windows PowerShell set keys with `$env:BL_CONSUMER_KEY="..."` instead of `export`.

Both downloaders are **resumable**: stop with Ctrl+C at any time and run the same command again.

### What to check in the test run (10 sets)
- **promoklocki**: `result` should be `ok`, `points` = number of table rows (~100+ for older sets),
  `last=` a date in 2026 and `rrp=` the catalog price. `parse_failed` for all 10 = the page layout changed again.
- **BrickLink**: `code=200` and a sensible `avg=`. `401` = wrong keys or token made for another IP.
  `400` for every set = query parameters need adjusting (see `PARAMS` in the script).

### Be polite to the sites
Keep the default delays (2.5–3.5 s for promoklocki, 1 s for BrickLink). Do not run several copies at once.
BrickLink has a daily API call limit; if it is reached the script stops and you continue the next day.

## Do not commit
- API keys (they are read from environment variables, never written to files);
- files over 100 MB (GitHub rejects them). The CSV outputs in `data/` should stay well below that.
