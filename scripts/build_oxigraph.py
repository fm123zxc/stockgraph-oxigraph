"""Build the local Oxigraph store from Financial-Knowledge-Graphs data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockgraph_oxigraph import build_store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("Financial-Knowledge-Graphs"),
        help="Path to the original Financial-Knowledge-Graphs checkout.",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=Path(".oxigraph") / "financial_kg",
        help="Directory for the Oxigraph persistent store.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear the target store before loading data.",
    )
    parser.add_argument(
        "--max-price-rows",
        type=int,
        default=None,
        help="Optional row limit per stock price CSV for quick test builds.",
    )
    parser.add_argument(
        "--max-news-rows",
        type=int,
        default=None,
        help="Optional row limit for latest_news.csv.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stats = build_store(
        args.source,
        args.store,
        clear=args.clear,
        max_price_rows=args.max_price_rows,
        max_news_rows=args.max_news_rows,
    )

    print(f"Oxigraph store: {args.store}")
    print(f"Inserted quads: {stats.quads}")
    if stats.rows:
        print("Loaded rows:")
        for name, count in sorted(stats.rows.items()):
            print(f"  {name}: {count}")
    if stats.skipped_files:
        print("Skipped optional inputs:")
        for path in stats.skipped_files:
            print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
