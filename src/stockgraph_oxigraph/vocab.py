"""RDF vocabulary for the financial knowledge graph."""

from __future__ import annotations

from pyoxigraph import NamedNode

BASE = "https://stockgraph.local/kg/"
EX = BASE
SCHEMA = "https://schema.org/"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"


def iri(value: str) -> NamedNode:
    return NamedNode(value)


def ex(term: str) -> NamedNode:
    return iri(EX + term)


def schema(term: str) -> NamedNode:
    return iri(SCHEMA + term)


def xsd(term: str) -> NamedNode:
    return iri(XSD + term)


def rdf(term: str) -> NamedNode:
    return iri(RDF + term)


def rdfs(term: str) -> NamedNode:
    return iri(RDFS + term)


PREFIXES = {
    "ex": EX,
    "schema": SCHEMA,
    "rdf": RDF,
    "rdfs": RDFS,
    "xsd": XSD,
}
