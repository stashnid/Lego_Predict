"""Re-download the REAL price history from promoklocki.pl up to today.

For every set that has a promoklocki URL in the original data, the script opens
the set's price-history page and saves every (date, price) point that the page's
chart contains. Nothing is interpolated or estimated:
  * a day without offers (null on the chart) is simply not saved,
  * a page that cannot be parsed is logged as 'parse_failed', not filled in.

Outputs (in update_2026/data/):
  promoklocki_daily.csv   url, set_no, date, price_pln       (raw chart points)
  promoklocki_status.csv  one line per page: http status, number of points,
                          first/last date, retail price found, scrape time (UTC)

The script is resumable: pages already listed in promoklocki_status.csv are
skipped, so you can stop it (Ctrl+C) and start again.

Usage:
  python promoklocki_update.py --limit 10 --verbose     # test run first!
  python promoklocki_update.py --only-retired --min-year 2014   # ~3.3k pages, ~3 h
  python promoklocki_update.py --only-retired                   # ~8.8k pages, ~8 h
  python promoklocki_update.py                                  # all ~10k pages
"""
import argparse
import csv
import random
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from common import OUT, load_sets

DAILY = OUT / "promoklocki_daily.csv"
STATUS = OUT / "promoklocki_status.csv"
STATUS_COLS = ["url", "set_no", "http_status", "result", "n_points", "first_date",
               "last_date", "pl_rrp_label", "pl_rrp", "scraped_at_utc"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (student statistics project, UCU)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5",
}
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
# Labels that promoklocki may use for the official LEGO price. Checked in the test run.
RRP_LABELS = ("cena katalogowa", "cena sugerowana", "cena regularna", "cena producenta")


def parse_history(html):
    """Return [(YYYY-MM-DD, price)] from the Google Charts `data.addRow(...)` calls.

    Same page format the original history_price_add.py relied on:
      data.addRow([new Date('2023-01-05'), parseFloat(1399.00) ...])   -> a price
      data.addRow([new Date('2023-01-06'), null])                      -> no offers, skipped
    """
    soup = BeautifulSoup(html, "lxml")
    points = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        if "data.addRow" not in text:
            continue
        for stmt in text.split(";"):
            stmt = stmt.strip()
            if not stmt.startswith("data.addRow"):
                continue
            d = DATE_RE.search(stmt)
            if not d or "parse" not in stmt:    # [date, null] = no offers that day
                continue
            after = stmt.split("parse", 1)[1].replace("'", "").replace('"', "")
            n = NUM_RE.search(after)
            if not n:
                continue
            price = float(n.group(1).replace(",", "."))
            if price > 0:
                points.append((d.group(1), price))
    return points


def parse_rrp(html):
    """Find the official retail price by its LABEL (not by cell position)."""
    soup = BeautifulSoup(html, "lxml")
    for cell in soup.find_all(["td", "th", "dt", "span", "div"]):
        label = cell.get_text(" ", strip=True).lower()
        if len(label) > 40 or not any(k in label for k in RRP_LABELS):
            continue
        nxt = cell.find_next(["td", "dd", "span", "strong", "div"])
        if nxt is None:
            continue
        m = re.search(r"(\d[\d\s]*[.,]\d{2})\s*zł", nxt.get_text(" ", strip=True))
        if m:
            return label, float(m.group(1).replace(" ", "").replace("\xa0", "").replace(",", "."))
    return None, None


def fetch(session, url, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            if r.status_code in (429, 503):           # the site asks us to slow down
                wait = 60 * (attempt + 1)
                print(f"  HTTP {r.status_code}, waiting {wait}s")
                time.sleep(wait)
                continue
            return r.status_code, r.text
        except requests.RequestException as e:
            print(f"  network error: {e}; retry in 20s")
            time.sleep(20)
    return None, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="process only N new pages (test run)")
    ap.add_argument("--only-retired", action="store_true", help="only retired sets")
    ap.add_argument("--min-year", type=int, help="only sets released in this year or later")
    ap.add_argument("--delay", type=float, default=2.5, help="seconds between requests (default 2.5)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    sets = load_sets()
    sets = sets[sets["has_pk_url"]]
    if args.only_retired:
        sets = sets[sets["is_retired"]]
    if args.min_year:
        sets = sets[sets["year"] >= args.min_year]
    # retired sets first, so a partial run already covers the most useful pages
    sets = sets.sort_values("is_retired", ascending=False).drop_duplicates("url_all_history")

    done = set()
    if STATUS.exists():
        with open(STATUS, newline="", encoding="utf-8") as f:
            done = {row["url"] for row in csv.DictReader(f)}
    todo = sets[~sets["url_all_history"].isin(done)]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"{len(done)} pages already done, {len(todo)} to go "
          f"(~{len(todo) * (args.delay + 1) / 3600:.1f} h)")

    new_daily, new_status = not DAILY.exists(), not STATUS.exists()
    with open(DAILY, "a", newline="", encoding="utf-8") as fd, \
         open(STATUS, "a", newline="", encoding="utf-8") as fs:
        wd, ws = csv.writer(fd), csv.DictWriter(fs, fieldnames=STATUS_COLS)
        if new_daily:
            wd.writerow(["url", "set_no", "date", "price_pln"])
        if new_status:
            ws.writeheader()

        session = requests.Session()
        consecutive_fail = 0
        for i, row in enumerate(todo.itertuples(), 1):
            url, set_no = row.url_all_history, row.set_no
            code, html = fetch(session, url)
            pts = parse_history(html) if code == 200 else []
            label, rrp = parse_rrp(html) if code == 200 else (None, None)
            if code != 200:
                result = "http_error"
            elif not pts and "data.addRow" not in html:
                result = "parse_failed"        # page layout changed or no chart at all
            elif not pts:
                result = "no_offers"
            else:
                result = "ok"
            for d, p in pts:
                wd.writerow([url, set_no, d, p])
            ws.writerow({
                "url": url, "set_no": set_no, "http_status": code, "result": result,
                "n_points": len(pts), "first_date": pts[0][0] if pts else "",
                "last_date": pts[-1][0] if pts else "", "pl_rrp_label": label or "",
                "pl_rrp": rrp if rrp is not None else "",
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            fd.flush(); fs.flush()

            if args.verbose or i % 50 == 0:
                last = f"{pts[-1][0]} = {pts[-1][1]} zł" if pts else "-"
                print(f"[{i}/{len(todo)}] {set_no:>10} {result:<12} points={len(pts):<5} "
                      f"last={last:<24} rrp={rrp} ({label})")

            consecutive_fail = consecutive_fail + 1 if result in ("http_error", "parse_failed") else 0
            if consecutive_fail >= 15:
                sys.exit("15 failures in a row: the site may block us or its layout changed. "
                         "Stopping. Check promoklocki_status.csv and the page in a browser.")
            time.sleep(args.delay + random.uniform(0, 1))

    print("Done.")


if __name__ == "__main__":
    main()
