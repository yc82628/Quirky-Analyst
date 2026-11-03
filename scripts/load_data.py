"""Load the Olist e-commerce CSVs into a DuckDB database with short table names.

Usage:
    python scripts/load_data.py data/raw/datasets data/olist.duckdb

Get the CSVs from Kaggle ("Brazilian E-Commerce Public Dataset by Olist")
or from https://github.com/olist/work-at-olist-data (datasets/ folder).
"""
import sys
from pathlib import Path

import duckdb

TABLES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

# Zip code prefixes have leading zeros, so keep them as text.
TYPE_OVERRIDES = {
    "customers": {"customer_zip_code_prefix": "VARCHAR"},
    "sellers": {"seller_zip_code_prefix": "VARCHAR"},
    "geolocation": {"geolocation_zip_code_prefix": "VARCHAR"},
}

# The original file has typos in two column names ("lenght"); fix them on load.
RENAMES = {
    "products": {
        "product_name_lenght": "product_name_length",
        "product_description_lenght": "product_description_length",
    },
}


def main(src: str, db_path: str = "olist.duckdb") -> None:
    src_dir = Path(src)
    con = duckdb.connect(db_path)
    for table, filename in TABLES.items():
        path = (src_dir / filename).as_posix()
        types = TYPE_OVERRIDES.get(table)
        types_sql = f", types={types!r}" if types else ""
        con.execute(
            f"CREATE OR REPLACE TABLE {table} AS "
            f"SELECT * FROM read_csv('{path}', header=true{types_sql})"
        )
        for old, new in RENAMES.get(table, {}).items():
            con.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
        n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"{table:22s} {n:>9,} rows")
    con.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:3])
