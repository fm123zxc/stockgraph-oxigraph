"""Export the local Oxigraph store to an RDF file."""

from __future__ import annotations

import argparse
from pathlib import Path

from pyoxigraph import NamedNode, RdfFormat, Store


DEFAULT_GRAPH_IRI = "https://stockgraph.local/kg/graph/main"


FORMATS = {
    "trig": RdfFormat.TRIG,
    "nq": RdfFormat.N_QUADS,
    "ttl": RdfFormat.TURTLE,
    "nt": RdfFormat.N_TRIPLES,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store",
        type=Path,
        default=Path(".oxigraph") / "financial_kg",
        help="Directory of the Oxigraph persistent store.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data") / "financial_kg.trig",
        help="Output RDF file.",
    )
    parser.add_argument(
        "--format",
        choices=sorted(FORMATS),
        default="trig",
        help="RDF serialization format.",
    )
    parser.add_argument(
        "--graph",
        default=DEFAULT_GRAPH_IRI,
        help="Named graph to export when using ttl or nt.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {}
    if args.format in {"ttl", "nt"}:
        kwargs["from_graph"] = NamedNode(args.graph)
    data = Store(str(args.store)).dump(format=FORMATS[args.format], **kwargs)
    args.output.write_bytes(data)
    print(f"Exported {args.output} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
