"""Re-download the REAL price history from promoklocki.pl up to today.

What the price is (checked on the site, November 2026): for each month (until
Oct 2025) and each week (from Nov 2025) the page lists "Najniższa cena" = the
LOWEST offer for a NEW set among the shops promoklocki tracks (LEGO.com, Allegro,
Empik Marketplace, Klockowo, foreign shops such as Rozetka ...). Amazon prices and
offers that need a discount code are excluded by the site. It is a price at which
the set could be BOUGHT, not a sale price.

For every set that has a promoklocki URL in the original data, the script opens
the history page and saves every row of that table. Nothing is interpolated:
  * a period without offers (empty price) is not saved,
  * a page without the history table is logged as 'parse_failed'.

Outputs (in update_2026/data/):
  promoklocki_history.csv  url, set_no, period_type (month/week), period_start,
                           lowest_price_pln, catalog_price_pln
  promoklocki_status.csv   one line per page: http status, number of rows,
                           first/last period, catalog price, scrape time (UTC)

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

DAILY = OUT / "promoklocki_history.csv"
STATUS = OUT / "promoklocki_status.csv"
STATUS_COLS = ["url", "set_no", "http_status", "result", "n_points", "first_date",
               "last_date", "pl_rrp_label", "pl_rrp", "scraped_at_utc"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (student statistics project, UCU)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5",
}
POLISH_MONTHS = {
    "stycz": 1, "lut": 2, "mar": 3, "kwie": 4, "maj": 5, "czerw": 6,
    "lip": 7, "sierp": 8, "wrze": 9, "październik": 10, "paźdz": 10, "listopad": 11,
    "grud": 12,
}
PRICE_RE = re.compile(r"(\d[\d\s\xa0]*,\d{2})\s*zł")


def _month_no(word):
    word = word.lower()
    for stem, n in POLISH_MONTHS.items():
        if word.startswith(stem):
            return n
    return None


def _price(text):
    m = PRICE_RE.search(text or "")
    return float(re.sub(r"[\s\xa0]", "", m.group(1)).replace(",", ".")) if m else None


def parse_period(label):
    """'marzec 2020' -> ('month', 2020-03-01); 'tydzień od 7 listopada 2026' -> ('week', 2026-11-07)."""
    label = label.strip().lower()
    m = re.match(r"tydzień od (\d{1,2}) (\S+) (\d{4})", label)
    if m:
        mon = _month_no(m.group(2))
        return ("week", f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}") if mon else (None, None)
    m = re.match(r"(\S+) (\d{4})$", label)
    if m:
        mon = _month_no(m.group(1))
        return ("month", f"{m.group(2)}-{mon:02d}-01") if mon else (None, None)
    return None, None


def parse_history(html):
    """Full price history from the table 'Data | Najniższa cena | Najniższa w historii | Cena katalogowa'.

    Page layout as checked in November 2026: one row per MONTH up to Oct 2025, then one row
    per WEEK. 'Najniższa cena' = the lowest offer in that month/week across the shops tracked
    by promoklocki (the site says Amazon prices and offers needing a discount code are excluded).
    Returns [(period_type, period_start 'YYYY-MM-DD', lowest_price, catalog_price)].
    """
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        head = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "najniższa cena" not in head or "cena katalogowa" not in head:
            continue
        i_low, i_cat = head.index("najniższa cena"), head.index("cena katalogowa")
        out = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) <= max(i_low, i_cat):
                continue
            ptype, start = parse_period(cells[0])
            low = _price(cells[i_low])
            if ptype and low:                       # no price = no offers, not saved
                out.append((ptype, start, low, _price(cells[i_cat])))
        return out
    return []


def parse_rrp(html):
    """Official LEGO price shown on the page as 'Cena katalogowa' (fact box at the top)."""
    soup = BeautifulSoup(html, "lxml")
    for lab in soup.select(".fact-label"):
        if "cena katalogowa" in lab.get_text(strip=True).lower():
            val = lab.find_next_sibling(class_="fact-value") or lab.find_next(class_="fact-value")
            p = _price(val.get_text(" ", strip=True)) if val else None
            if p:
                return "cena katalogowa", p
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
            wd.writerow(["url", "set_no", "period_type", "period_start", "lowest_price_pln", "catalog_price_pln"])
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
            elif not pts and "najniższa cena" not in html.lower():
                result = "parse_failed"        # page layout changed or no chart at all
            elif not pts:
                result = "no_offers"
            else:
                result = "ok"
            for row_ in pts:
                wd.writerow([url, set_no, *row_])
            ws.writerow({
                "url": url, "set_no": set_no, "http_status": code, "result": result,
                "n_points": len(pts), "first_date": pts[0][1] if pts else "",
                "last_date": pts[-1][1] if pts else "", "pl_rrp_label": label or "",
                "pl_rrp": rrp if rrp is not None else "",
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            fd.flush(); fs.flush()

            if args.verbose or i % 50 == 0:
                last = f"{pts[-1][1]} = {pts[-1][2]} zł" if pts else "-"
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
