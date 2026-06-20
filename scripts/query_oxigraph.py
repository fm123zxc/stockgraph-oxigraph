"""Run a SPARQL query against the local Oxigraph store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pyoxigraph import QueryBoolean, QuerySolutions, QueryTriples, RdfFormat, Store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockgraph_oxigraph.vocab import PREFIXES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "query",
        nargs="?",
        type=Path,
        help="Path to a .sparql file. If omitted, --sparql must be provided.",
    )
    parser.add_argument(
        "--sparql",
        help="SPARQL query text.",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=Path(".oxigraph") / "financial_kg",
        help="Directory of the Oxigraph persistent store.",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "nt"],
        default="table",
        help="Output format.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    query = load_query(args.query, args.sparql)
    result = Store(str(args.store)).query(query, prefixes=PREFIXES, use_default_graph_as_union=True)

    if isinstance(result, QuerySolutions):
        print_solutions(result, args.format)
    elif isinstance(result, QueryBoolean):
        print(bool(result))
    elif isinstance(result, QueryTriples):
        serialized = result.serialize(format=RdfFormat.N_TRIPLES)
        print(serialized.decode("utf-8") if isinstance(serialized, bytes) else serialized)
    else:
        print(result)
    return 0


def load_query(path: Path | None, query_text: str | None) -> str:
    if query_text:
        return query_text
    if path:
        return path.read_text(encoding="utf-8")
    raise SystemExit("Provide a query file or --sparql text.")


def print_solutions(result: QuerySolutions, output_format: str) -> None:
    variables = [variable.value for variable in result.variables]
    rows = []
    for solution in result:
        row = {}
        for variable in variables:
            try:
                value = solution[variable]
            except KeyError:
                value = None
            row[variable] = term_to_text(value)
        rows.append(row)

    if output_format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if output_format == "nt":
        raise SystemExit("--format nt is only valid for CONSTRUCT/DESCRIBE queries.")

    print_table(variables, rows)


def print_table(variables: list[str], rows: list[dict[str, str]]) -> None:
    if not variables:
        return
    widths = {
        variable: max(
            len("?" + variable),
            *(len(row.get(variable, "")) for row in rows),
        )
        for variable in variables
    }
    header = "  ".join(("?" + variable).ljust(widths[variable]) for variable in variables)
    print(header)
    print("  ".join("-" * widths[variable] for variable in variables))
    for row in rows:
        print("  ".join(row.get(variable, "").ljust(widths[variable]) for variable in variables))


def term_to_text(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.startswith("<") and text.endswith(">"):
        return text[1:-1]
    return text


if __name__ == "__main__":
    raise SystemExit(main())
