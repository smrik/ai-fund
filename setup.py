"""
Alpha Pod — Setup
Run this once to initialize the database and load your starter universe.

Usage:
    cd alpha-pod
    python setup.py
"""
import csv
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import UNIVERSE_PATH, DB_PATH
from db.schema import create_tables, get_connection
from db.loader import upsert_universe


def main():
    print("=" * 50)
    print("ALPHA POD — Initial Setup")
    print("=" * 50)
    print()

    # Step 1: Create database and tables
    print("1. Creating database...")
    conn = get_connection()
    create_tables(conn)
    print()

    # Step 2: Load universe from CSV
    print("2. Loading universe from CSV...")
    if not UNIVERSE_PATH.exists():
        print(f"   ⚠ Universe file not found at {UNIVERSE_PATH}")
        print("   Create it and re-run setup.")
        conn.close()
        return

    with open(UNIVERSE_PATH, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Clean up numeric fields
    for row in rows:
        mcap = row.get("market_cap_mm", "")
        row["market_cap_mm"] = float(mcap) if mcap else None

    upsert_universe(conn, rows)
    print(f"   ✓ Loaded {len(rows)} names into universe")
    print()

    # Step 3: Verify
    print("3. Verification:")
    cur = conn.execute("SELECT COUNT(*) FROM universe")
    count = cur.fetchone()[0]
    print(f"   Universe:   {count} names")

    cur = conn.execute("SELECT COUNT(*) FROM financials")
    count = cur.fetchone()[0]
    print(f"   Financials: {count} records (empty — run CIQ refresh to populate)")

    cur = conn.execute("SELECT COUNT(*) FROM prices")
    count = cur.fetchone()[0]
    print(f"   Prices:     {count} records (empty — run IBKR price pull to populate)")

    print()
    print("=" * 50)
    print("Setup complete. Next steps:")
    print()
    print("  1. Edit config/universe.csv with your actual watchlist")
    print("  2. Run:  python -m pipeline.pull_prices    (IBKR must be running)")
    print("  3. Run:  python -m ciq.ciq_refresh          (Excel + CIQ must be open)")
    print("=" * 50)

    conn.close()


if __name__ == "__main__":
    main()
