# Data update to 2026 (promoklocki.pl + BrickLink)

Forked from [BartekPodgorski/Lego_Predict](https://github.com/BartekPodgorski/Lego_Predict)
(data collection by Bartosz Podgórski and Wiktoria Szczepańska). Everything in this folder
is our addition; the original files in the repository root are not modified.

## What is collected — real data only

| Script | Source | What it saves |
|---|---|---|
| `promoklocki_update.py` | promoklocki.pl (lowest offers in Polish shops, PLN) | every daily point of each set's price chart, up to the day you run it |
| `bricklink_prices.py` | BrickLink API price guide | average price of **actual sales** of new sets in Europe in the last 6 months (EUR, incl. VAT) |
| `merge_2026.py` | the two files above + original Brickset table | one row per set, `lego_2026_merged.csv` |

Rules the scripts follow:
- nothing is interpolated, estimated or generated; a missing value stays empty;
- a day with no offers (`null` on the chart) is not saved — the original scripts saved it as price 0;
- monthly price = **mean** of the daily points (the original used the monthly maximum, which biases prices up);
- every line has the time it was downloaded (`scraped_at_utc`, `fetched_at_utc`), so it is visible that the data are current;
- the old `PL_retailPrice` is used only when it is a plain number: in ~2.9k rows the original scraper took
  a wrong table cell (another set's price). The new scraper looks for the retail price by its label.

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
- **promoklocki**: `result` should be `ok` and `last=` should show a 2026 date for sets still on sale.
  If you get `parse_failed` for all 10, the site changed its page layout — stop and send us the output.
  `rrp=None` means the retail-price label was not found; history is still saved.
- **BrickLink**: `code=200` and a sensible `avg=`. `401` = wrong keys or token made for another IP.
  `400` for every set = query parameters need adjusting (see `PARAMS` in the script).

### Be polite to the sites
Keep the default delays (2.5–3.5 s for promoklocki, 1 s for BrickLink). Do not run several copies at once.
BrickLink has a daily API call limit; if it is reached the script stops and you continue the next day.

## Do not commit
- API keys (they are read from environment variables, never written to files);
- files over 100 MB (GitHub rejects them). The CSV outputs in `data/` should stay well below that.
