#!/usr/bin/env python
import os, sys, time, json, argparse, pathlib, datetime as dt
from typing import List, Dict
import pandas as pd

# Import your site scrapers (update names if different)
import scrape_craigslist as cl
import scrape_carscom as ccom
import scrape_cargurus as cg
import config

OUTPUT_DIR = pathlib.Path(os.getenv("OUTPUT_DIR", "./data/out"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def canonical_url(u: str) -> str:
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    s = urlsplit(u)
    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urlunsplit((s.scheme, s.netloc, s.path, urlencode(q, doseq=True), ""))

def as_df(rows: List[Dict]) -> pd.DataFrame:
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "url" in df: df["url"] = df["url"].map(canonical_url)
    for col in ("price","mileage"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    if "source" in df: df["source"] = df["source"].astype("category")
    if "first_seen" not in df:
        df["first_seen"] = dt.datetime.utcnow().isoformat(timespec="seconds")
    return df

def apply_filters(df: pd.DataFrame, price_max: int, miles_max: int) -> pd.DataFrame:
    if "price" in df:
        df = df[(df["price"].isna()) | (df["price"] <= price_max)]
    if "mileage" in df:
        df = df[(df["mileage"].isna()) | (df["mileage"] <= miles_max)]
    return df

def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    if "url" in df:
        df = df.drop_duplicates("url", keep="first")
    return df

def scrape_site(site_name: str, fn) -> pd.DataFrame:
    print(f"→ {site_name}…", flush=True)
    try:
        rows = fn.scrape()  # assumes each module exposes scrape()
        df = as_df(rows)
        print(f"  {site_name}: {len(df)} rows")
        return df
    except Exception as e:
        print(f"  {site_name} failed: {e}", file=sys.stderr)
        return pd.DataFrame()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default=os.getenv("ZIP_CODE","19103"))
    ap.add_argument("--radius", type=int, default=int(os.getenv("RADIUS_MILES","200")))
    ap.add_argument("--price-max", type=int, default=int(os.getenv("PRICE_MAX","4000")))
    ap.add_argument("--miles-max", type=int, default=int(os.getenv("MILEAGE_MAX","200000")))
    ap.add_argument("--pages", type=int, default=int(os.getenv("MAX_PAGES","8")))
    ap.add_argument("--sites", default="craigslist,carscom,cargurus")
    ap.add_argument("--no-parquet", action="store_true")
    args = ap.parse_args()

    # Propagate run-time config to modules and shared config
    settings = dict(ZIP_CODE=args.zip, RADIUS_MILES=args.radius, PRICE_MAX=args.price_max,
                    MILEAGE_MAX=args.miles_max, MAX_PAGES=args.pages)
    for k, v in settings.items():
        setattr(config, k, v)
    for mod in (cl, ccom, cg):
        for k, v in settings.items():
            if hasattr(mod, k): setattr(mod, k, v)

    dfs = []
    for name, mod in [("craigslist", cl), ("carscom", ccom), ("cargurus", cg)]:
        if name not in args.sites: continue
        df = scrape_site(name, mod)
        if not df.empty:
            out_csv = OUTPUT_DIR / f"{name}.csv"
            df.to_csv(out_csv, index=False)
            if not args.no_parquet:
                df.to_parquet(OUTPUT_DIR / f"{name}.parquet", index=False)
            dfs.append(df)

    if dfs:
        combined = dedupe(pd.concat(dfs, ignore_index=True))
        combined = apply_filters(combined, args.price_max, args.miles_max)
        combined.sort_values(["price","mileage"], na_position="last", inplace=True)
        ts = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        combined_csv = OUTPUT_DIR / f"combined-{ts}.csv"
        combined.to_csv(combined_csv, index=False)
        if not args.no_parquet:
            combined.to_parquet(OUTPUT_DIR / f"combined-{ts}.parquet", index=False)

        print("\n=== Summary ===")
        print(combined.groupby("source")["url"].count())
        print(f"\nCombined: {len(combined)} rows → {combined_csv}")
    else:
        print("No data scraped.")

if __name__ == "__main__":
    main()
