# Financial Knowledge Graphs with Oxigraph

This root project refactors the original `Financial-Knowledge-Graphs` Neo4j notebook flow into a local RDF graph backed by Oxigraph.

## What Changed

The original repository builds property-graph nodes and relationships with `py2neo`:

- `股票`, `股东`, `概念`, `公告`, `沪股通`, `深股通`
- relationships such as `参股`, `概念属于`, `发布公告`, `成分股属于`, and stock correlation edges

This refactor stores the same domain as RDF triples/quads:

- entities become IRIs under `https://stockgraph.local/kg/`
- labels and human text use `rdfs:label` / `schema:*`
- relationships become RDF predicates such as `ex:holds`, `ex:belongsToConcept`, `ex:publishedAnnouncement`, `ex:memberOf`
- queries use SPARQL instead of Cypher

## Install

```powershell
pip install -r requirements.txt
```

## Build The Store

Run from `C:\code\stockgraph`:

```powershell
python scripts\build_oxigraph.py --clear
```

For a quick smoke test:

```powershell
python scripts\build_oxigraph.py --clear --max-price-rows 50 --max-news-rows 20
```

The default persistent store is:

```text
.oxigraph\financial_kg
```

## Query

```powershell
python scripts\query_oxigraph.py queries\list_stocks.sparql
python scripts\query_oxigraph.py queries\latest_prices.sparql
python scripts\query_oxigraph.py queries\news_sample.sparql
```

Inline query example:

```powershell
python scripts\query_oxigraph.py --sparql "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
```

Open one command against the persistent store at a time. Oxigraph uses RocksDB
under the hood, and parallel Python processes can contend for the same store
lock on Windows.

## Export RDF

```powershell
python scripts\export_rdf.py --output data\financial_kg.trig --format trig
```

Use `--format ttl`, `nt`, or `nq` for other serializations.

## Visualize With AntV G6

Generate an interactive HTML graph from the Oxigraph store:

```powershell
python scripts\visualize_g6.py
```

Open the generated file in a browser:

```text
data\financial_kg_g6.html
```

Useful limits:

```powershell
python scripts\visualize_g6.py --max-days-per-stock 12 --max-news 20
```

## Data Inputs

The builder loads the CSV files currently present in `Financial-Knowledge-Graphs\data`:

- `*.XSHE.csv` / `*.XSHG.csv` stock price files
- `latest_news.csv`

It also supports optional CSVs from the original notebooks if they are later restored:

- `stock_basic.csv`
- `holders.csv` / `stock_holders.csv`
- `concept.csv`
- `stock_concept.csv`
- `sh.csv`
- `sz.csv`
- `corr.csv`
- `financial_data\notices\*.csv`

Missing optional inputs are reported and skipped.
