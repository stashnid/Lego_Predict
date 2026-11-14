"""Shared helpers for the 2026 data update.

Everything here only READS the original files of the repository
(lego_retail_price.xlsx). Nothing is generated or imputed.
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent      # repository root
OUT = Path(__file__).resolve().parent / "data"     # where new files are written
OUT.mkdir(exist_ok=True)

_PRICE_RE = re.compile(r"^\s*(\d+(?:[.,]\d{1,2})?)\s*$")


def parse_old_pl_rrp(raw):
    """Old PL_retailPrice column from the original scrape.

    The original script took the 24th <td> of the page. For ~2.9k sets that
    cell was NOT the retail price but a link to another set's price history
    (strings containing 'Historia cen'). Only plain numbers like '1099,99'
    are accepted here; everything else becomes None.
    """
    if not isinstance(raw, str):
        return None
    m = _PRICE_RE.match(raw)
    return float(m.group(1).replace(",", ".")) if m else None


def retired_date(row):
    """Last-available date: Germany first (EU market), then UK, then US."""
    for col in ("DE_dateLastAvailable", "UK_dateLastAvailable", "US_dateLastAvailable"):
        v = row.get(col)
        if isinstance(v, str) and v:
            return pd.to_datetime(v).tz_localize(None).normalize(), col[:2]
    return pd.NaT, None


def load_sets():
    """One row per set from the original Brickset + promoklocki link table."""
    df = pd.read_excel(ROOT / "lego_retail_price.xlsx")
    df["set_no"] = df["number"].astype(str) + "-" + df["numberVariant"].astype(int).astype(str)
    df["pl_rrp_old"] = df["PL_retailPrice"].map(parse_old_pl_rrp)
    rd = df.apply(retired_date, axis=1, result_type="expand")
    df["retired_date"], df["retired_source"] = rd[0], rd[1]
    df["is_retired"] = df["retired_date"].notna() | (df["status"] == "Produkt wycofany")
    df["has_pk_url"] = df["url_all_history"].astype(str).str.startswith("https")
    return df
