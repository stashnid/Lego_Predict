"""Join Brickset features + promoklocki history + BrickLink prices into one table.

Input : the original lego_retail_price.xlsx and the files written by
        promoklocki_update.py / bricklink_prices.py (any of them may be missing).
Output: update_2026/data/lego_2026_merged.csv, one row per set.

Only observed values are used. When a value is not observed (no offers in that
month, no BrickLink sales, no retail price) the cell stays empty (NaN).
No interpolation, no imputation, no filtering of outliers here - cleaning is
done and documented in the analysis notebook.

Columns added:
  pl_rrp            PLN retail price: new scrape (by label) if found, else old value
                    if it was a plain number, else empty
  pk_months         number of months with at least one offer
  pk_first_month, pk_last_month
  pk_last_price     mean of daily lowest offers in the last observed month (PLN)
  pk_price_y1/y2/y3 mean price in the calendar month exactly 1/2/3 years after
                    retirement (empty if no offers in that month)
  growth_pk         pk_last_price / pl_rrp
  bl_avg_new        BrickLink average sold price, new, last 6 months (EUR, incl. VAT)
  bl_qty_new        number of units sold in those 6 months
  bl_last_sale      date of the most recent sale in the guide
  growth_bl         bl_avg_new / DE_retailPrice   (both EUR incl. VAT)
  years_since_retired  from retirement date to the last observed price
"""
import pandas as pd

from common import OUT, load_sets

KEEP = ["set_no", "number", "numberVariant", "name", "year", "theme", "themeGroup", "subtheme",
        "category", "pieces", "minifigs", "ownedBy", "wantedBy", "rating", "reviewCount",
        "availability", "packagingType", "US_retailPrice", "UK_retailPrice", "DE_retailPrice",
        "retired_date", "retired_source", "is_retired", "status", "url_all_history"]


def promoklocki_features(sets):
    daily_f, status_f = OUT / "promoklocki_daily.csv", OUT / "promoklocki_status.csv"
    if not daily_f.exists():
        print("promoklocki_daily.csv not found - skipping promoklocki columns")
        return pd.DataFrame(columns=["url_all_history"])
    daily = pd.read_csv(daily_f, parse_dates=["date"]).drop_duplicates(["url", "date"])
    daily["month"] = daily["date"].dt.to_period("M")
    monthly = daily.groupby(["url", "month"])["price_pln"].mean().rename("price").reset_index()

    feats = monthly.sort_values("month").groupby("url").agg(
        pk_months=("price", "size"),
        pk_first_month=("month", "first"),
        pk_last_month=("month", "last"),
        pk_last_price=("price", "last"),
    )
    # price exactly k years after retirement (same calendar month), observed values only
    ret = sets.dropna(subset=["retired_date"]).drop_duplicates("url_all_history") \
              .set_index("url_all_history")["retired_date"]
    lookup = monthly.set_index(["url", "month"])["price"]
    for k in (1, 2, 3):
        vals = {}
        for url, d in ret.items():
            key = (url, (d + pd.DateOffset(years=k)).to_period("M"))
            vals[url] = lookup.get(key)
        feats[f"pk_price_y{k}"] = pd.Series(vals)

    if status_f.exists():
        st = pd.read_csv(status_f).drop_duplicates("url", keep="last").set_index("url")
        feats = feats.join(st[["pl_rrp", "result"]].rename(
            columns={"pl_rrp": "pl_rrp_new", "result": "pk_result"}), how="outer")
    return feats.rename_axis("url_all_history").reset_index()


def bricklink_features():
    f = OUT / "bricklink_prices.csv"
    if not f.exists():
        print("bricklink_prices.csv not found - skipping BrickLink columns")
        return pd.DataFrame(columns=["set_no"])
    bl = pd.read_csv(f, dtype={"set_no": str})
    bl = bl[(bl["guide_type"] == "sold") & (bl["new_or_used"] == "N")]
    bl = bl.drop_duplicates("set_no", keep="last")
    for c in ("avg_price", "qty_avg_price", "total_quantity"):
        bl[c] = pd.to_numeric(bl[c], errors="coerce")
    bl.loc[bl["total_quantity"].fillna(0) == 0, ["avg_price", "qty_avg_price"]] = None
    return bl.rename(columns={"avg_price": "bl_avg_new", "qty_avg_price": "bl_qty_avg_new",
                              "total_quantity": "bl_qty_new", "last_sale": "bl_last_sale",
                              "fetched_at_utc": "bl_fetched_at"})[
        ["set_no", "bl_avg_new", "bl_qty_avg_new", "bl_qty_new", "bl_last_sale", "bl_fetched_at"]]


def main():
    sets = load_sets()
    df = sets[KEEP + ["pl_rrp_old"]].copy()
    df = df.merge(promoklocki_features(sets), on="url_all_history", how="left")
    df = df.merge(bricklink_features(), on="set_no", how="left")

    new = pd.to_numeric(df.get("pl_rrp_new"), errors="coerce") if "pl_rrp_new" in df else None
    df["pl_rrp"] = new.fillna(df["pl_rrp_old"]) if new is not None else df["pl_rrp_old"]
    df["pl_rrp_source"] = "old_plain_number"
    if new is not None:
        df.loc[new.notna(), "pl_rrp_source"] = "new_scrape_label"
    df.loc[df["pl_rrp"].isna(), "pl_rrp_source"] = ""

    if "pk_last_price" in df:
        df["growth_pk"] = df["pk_last_price"] / df["pl_rrp"]
        last = df["pk_last_month"].map(lambda p: p.to_timestamp() if pd.notna(p) else pd.NaT)
        df["years_since_retired"] = (last - df["retired_date"]).dt.days / 365.25
    if "bl_avg_new" in df:
        df["growth_bl"] = df["bl_avg_new"] / df["DE_retailPrice"]

    out = OUT / "lego_2026_merged.csv"
    df.to_csv(out, index=False)
    print(f"Saved {out} : {len(df)} sets, {df.shape[1]} columns")
    for c in ("growth_pk", "growth_bl"):
        if c in df:
            print(f"  {c}: observed for {df[c].notna().sum()} sets, median {df[c].median():.2f}")


if __name__ == "__main__":
    main()
