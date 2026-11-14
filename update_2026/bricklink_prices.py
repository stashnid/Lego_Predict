"""Download the CURRENT market price of each set from the BrickLink price guide.

BrickLink's price guide = actual completed sales between collectors in the
last 6 months (guide_type=sold). One API call per set; the response is saved
as-is. Nothing is estimated: a set without sales gets empty prices.

Setup (once, by the person who runs it):
  1. Log in on bricklink.com, open the API page (https://www.bricklink.com/v3/api.page),
     accept the API Terms of Use, register as a consumer and create an Access Token
     for YOUR current public IP address (the token only works from that IP).
  2. Put the four keys into environment variables (never commit them!):
       BL_CONSUMER_KEY  BL_CONSUMER_SECRET  BL_TOKEN  BL_TOKEN_SECRET
  3. pip install -r requirements.txt

Usage:
  python bricklink_prices.py --limit 10 --verbose     # test run first!
  python bricklink_prices.py --only-retired --min-year 2014   # same sets as promoklocki
  python bricklink_prices.py                          # all sets with a retail price

Output (update_2026/data/bricklink_prices.csv), one line per set and query:
  set_no, guide_type, new_or_used, region, currency, vat, avg_price,
  qty_avg_price, min_price, max_price, unit_quantity, total_quantity,
  first_sale, last_sale, meta_code, meta_message, fetched_at_utc

Resumable: (set_no, new_or_used, guide_type) already in the file are skipped.
BrickLink limits the number of API calls per day; if the limit is hit the
script stops cleanly, just run it again the next day.

!! CHECK ON THE TEST RUN: the query parameters below (region='europe',
currency_code='EUR', vat='Y') follow the BrickLink API docs as I know them.
If the test run returns meta_code 400 for every set, compare them with
https://www.bricklink.com/v3/api.page?page=get-price-guide and adjust PARAMS.
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone

from requests_oauthlib import OAuth1Session

from common import OUT, load_sets

BASE = "https://api.bricklink.com/api/store/v1"
FILE = OUT / "bricklink_prices.csv"
COLS = ["set_no", "guide_type", "new_or_used", "region", "currency", "vat", "avg_price",
        "qty_avg_price", "min_price", "max_price", "unit_quantity", "total_quantity",
        "first_sale", "last_sale", "meta_code", "meta_message", "fetched_at_utc"]
PARAMS = {"region": "europe", "currency_code": "EUR", "vat": "Y"}  # prices incl. VAT, like RRP


def session_from_env():
    keys = ["BL_CONSUMER_KEY", "BL_CONSUMER_SECRET", "BL_TOKEN", "BL_TOKEN_SECRET"]
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing environment variables: {', '.join(missing)} (see the docstring)")
    return OAuth1Session(os.environ["BL_CONSUMER_KEY"], os.environ["BL_CONSUMER_SECRET"],
                         os.environ["BL_TOKEN"], os.environ["BL_TOKEN_SECRET"])


def price_guide(sess, set_no, guide_type, new_or_used):
    r = sess.get(f"{BASE}/items/SET/{set_no}/price",
                 params={"guide_type": guide_type, "new_or_used": new_or_used, **PARAMS},
                 timeout=30)
    try:
        j = r.json()
    except ValueError:
        return {"meta_code": r.status_code, "meta_message": r.text[:200]}
    meta, data = j.get("meta", {}), j.get("data") or {}
    dates = sorted(d.get("date_ordered", "") for d in data.get("price_detail", [])
                   if d.get("date_ordered"))
    return {
        "avg_price": data.get("avg_price"), "qty_avg_price": data.get("qty_avg_price"),
        "min_price": data.get("min_price"), "max_price": data.get("max_price"),
        "unit_quantity": data.get("unit_quantity"), "total_quantity": data.get("total_quantity"),
        "first_sale": dates[0][:10] if dates else "", "last_sale": dates[-1][:10] if dates else "",
        "meta_code": meta.get("code", r.status_code), "meta_message": meta.get("message", ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="process only N new sets (test run)")
    ap.add_argument("--only-retired", action="store_true")
    ap.add_argument("--min-year", type=int, help="only sets released in this year or later")
    ap.add_argument("--also-used", action="store_true", help="also query used-condition sales")
    ap.add_argument("--also-stock", action="store_true", help="also query current listings")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    sets = load_sets()
    sets = sets[sets["DE_retailPrice"].notna() | sets["pl_rrp_old"].notna()]
    if args.only_retired:
        sets = sets[sets["is_retired"]]
    if args.min_year:
        sets = sets[sets["year"] >= args.min_year]
    sets = sets.sort_values("is_retired", ascending=False).drop_duplicates("set_no")

    queries = [("sold", "N")]
    if args.also_used:
        queries.append(("sold", "U"))
    if args.also_stock:
        queries.append(("stock", "N"))

    done = set()
    if FILE.exists():
        with open(FILE, newline="", encoding="utf-8") as f:
            done = {(r["set_no"], r["guide_type"], r["new_or_used"]) for r in csv.DictReader(f)}
    todo = [(s, g, n) for s in sets["set_no"] for g, n in queries if (s, g, n) not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(done)} queries already done, {len(todo)} to go")

    sess = session_from_env()
    new_file = not FILE.exists()
    with open(FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new_file:
            w.writeheader()
        errors = 0
        for i, (set_no, g, n) in enumerate(todo, 1):
            res = price_guide(sess, set_no, g, n)
            w.writerow({"set_no": set_no, "guide_type": g, "new_or_used": n,
                        "region": PARAMS["region"], "currency": PARAMS["currency_code"],
                        "vat": PARAMS["vat"],
                        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        **res})
            f.flush()
            code = int(res.get("meta_code") or 0)
            if args.verbose or i % 100 == 0:
                print(f"[{i}/{len(todo)}] {set_no:>10} {g}/{n} code={code} "
                      f"avg={res.get('avg_price')} sold_qty={res.get('total_quantity')} "
                      f"{res.get('meta_message', '')}")
            if code == 401:
                sys.exit("401 Unauthorized: wrong keys, or the token was made for another IP.")
            if code == 429 or "limit" in str(res.get("meta_message", "")).lower():
                sys.exit("Daily API limit reached. Progress is saved; run again tomorrow.")
            errors = errors + 1 if code not in (200, 404) else 0   # 404 = set unknown to BrickLink
            if errors >= 20:
                sys.exit("20 errors in a row, stopping. Look at meta_message in the CSV.")
            time.sleep(args.delay)
    print("Done.")


if __name__ == "__main__":
    main()
