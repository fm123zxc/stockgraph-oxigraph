"""Generate an AntV G6 HTML visualization from the Oxigraph store."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from pyoxigraph import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockgraph_oxigraph.vocab import PREFIXES


NODE_STYLES = {
    "Root": {"fill": "#111827", "stroke": "#111827", "size": 44},
    "Stock": {"fill": "#2563eb", "stroke": "#1d4ed8", "size": 36},
    "TradingDay": {"fill": "#10b981", "stroke": "#059669", "size": 16},
    "NewsHub": {"fill": "#475569", "stroke": "#334155", "size": 32},
    "NewsArticle": {"fill": "#f59e0b", "stroke": "#d97706", "size": 22},
    "Shareholder": {"fill": "#ef4444", "stroke": "#dc2626", "size": 28},
    "Concept": {"fill": "#8b5cf6", "stroke": "#7c3aed", "size": 28},
    "MarketConnect": {"fill": "#06b6d4", "stroke": "#0891b2", "size": 28},
    "Announcement": {"fill": "#f97316", "stroke": "#ea580c", "size": 24},
    "Correlation": {"fill": "#64748b", "stroke": "#475569", "size": 20},
}

EDGE_STYLES = {
    "containsStock": {"stroke": "#94a3b8", "lineWidth": 1.4},
    "containsNews": {"stroke": "#94a3b8", "lineWidth": 1.4},
    "hasTradingDay": {"stroke": "#34d399", "lineWidth": 1.2},
    "hasNews": {"stroke": "#fbbf24", "lineWidth": 1.2},
    "holds": {"stroke": "#f87171", "lineWidth": 1.5},
    "belongsToConcept": {"stroke": "#a78bfa", "lineWidth": 1.5},
    "memberOf": {"stroke": "#22d3ee", "lineWidth": 1.5},
    "publishedAnnouncement": {"stroke": "#fb923c", "lineWidth": 1.4},
    "correlatedWith": {"stroke": "#64748b", "lineWidth": 1.6},
}

RELATION_LABELS = {
    "containsStock": "股票",
    "containsNews": "新闻流",
    "hasTradingDay": "交易日",
    "hasNews": "新闻",
    "holds": "参股",
    "belongsToConcept": "概念",
    "memberOf": "成分股",
    "publishedAnnouncement": "公告",
    "correlatedWith": "相关",
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
        default=Path("data") / "financial_kg_g6.html",
        help="Output HTML file.",
    )
    parser.add_argument(
        "--max-days-per-stock",
        type=int,
        default=24,
        help="Latest trading-day nodes to show for each stock.",
    )
    parser.add_argument(
        "--max-news",
        type=int,
        default=30,
        help="Latest news nodes to show.",
    )
    parser.add_argument(
        "--max-relationships",
        type=int,
        default=200,
        help="Optional entity relationship edges to show.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = Store(str(args.store))
    graph = build_graph_payload(
        store,
        max_days_per_stock=args.max_days_per_stock,
        max_news=args.max_news,
        max_relationships=args.max_relationships,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(graph), encoding="utf-8")
    print(f"Generated {args.output}")
    print(f"Nodes: {len(graph['nodes'])}, edges: {len(graph['edges'])}")
    return 0


def build_graph_payload(
    store: Store,
    *,
    max_days_per_stock: int,
    max_news: int,
    max_relationships: int,
) -> dict:
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    add_node(nodes, "kg:root", "金融知识图谱", "Root", {"summary": "Oxigraph RDF store"})
    add_node(nodes, "kg:news", "财经新闻", "NewsHub", {"summary": "latest_news.csv"})
    add_edge(edges, "kg:root", "kg:news", "containsNews")

    add_stock_days(store, nodes, edges, max_days_per_stock)
    add_news(store, nodes, edges, max_news)
    add_optional_relationships(store, nodes, edges, max_relationships)

    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "byType": count_by_type(nodes.values()),
        },
    }


def add_stock_days(
    store: Store,
    nodes: dict[str, dict],
    edges: dict[str, dict],
    max_days_per_stock: int,
) -> None:
    query = """
PREFIX ex: <https://stockgraph.local/kg/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?stock ?stockLabel ?day ?tradeDate ?open ?close ?high ?low ?volume
WHERE {
  ?stock a ex:Stock ;
         ex:hasTradingDay ?day .
  ?day ex:tradeDate ?tradeDate .
  OPTIONAL { ?stock rdfs:label ?stockLabel }
  OPTIONAL { ?day ex:open ?open }
  OPTIONAL { ?day ex:close ?close }
  OPTIONAL { ?day ex:high ?high }
  OPTIONAL { ?day ex:low ?low }
  OPTIONAL { ?day ex:volume ?volume }
}
ORDER BY ?stock DESC(?tradeDate)
"""
    grouped: dict[str, list[dict]] = defaultdict(list)
    stock_labels: dict[str, str] = {}
    for row in store.query(query, prefixes=PREFIXES, use_default_graph_as_union=True):
        stock_id = term_text(row["stock"])
        stock_labels[stock_id] = clean_literal(row["stockLabel"]) or iri_tail(stock_id)
        grouped[stock_id].append(
            {
                "day": term_text(row["day"]),
                "tradeDate": clean_literal(row["tradeDate"]),
                "open": clean_literal(row["open"]),
                "close": clean_literal(row["close"]),
                "high": clean_literal(row["high"]),
                "low": clean_literal(row["low"]),
                "volume": clean_literal(row["volume"]),
            }
        )

    for stock_id, rows in grouped.items():
        label = stock_labels.get(stock_id) or iri_tail(stock_id)
        add_node(nodes, stock_id, label, "Stock", {"iri": stock_id})
        add_edge(edges, "kg:root", stock_id, "containsStock")
        for item in sorted(rows, key=lambda value: value["tradeDate"] or "", reverse=True)[:max_days_per_stock]:
            day_id = item["day"]
            day_label = item["tradeDate"] or iri_tail(day_id)
            close = item.get("close")
            if close:
                day_label = f"{day_label} 收 {close}"
            add_node(nodes, day_id, day_label, "TradingDay", item | {"iri": day_id})
            add_edge(edges, stock_id, day_id, "hasTradingDay")


def add_news(store: Store, nodes: dict[str, dict], edges: dict[str, dict], max_news: int) -> None:
    query = f"""
PREFIX ex: <https://stockgraph.local/kg/>
PREFIX schema: <https://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?news ?publishedAt ?title ?summary
WHERE {{
  ?news a ex:NewsArticle .
  OPTIONAL {{ ?news schema:datePublished ?publishedAt }}
  OPTIONAL {{ ?news schema:headline ?title }}
  OPTIONAL {{ ?news rdfs:label ?summary }}
}}
ORDER BY DESC(?publishedAt)
LIMIT {int(max_news)}
"""
    for row in store.query(query, prefixes=PREFIXES, use_default_graph_as_union=True):
        news_id = term_text(row["news"])
        published_at = clean_literal(row["publishedAt"])
        title = clean_literal(row["title"]) or clean_literal(row["summary"]) or iri_tail(news_id)
        label = compact_label(title, 38)
        if published_at:
            label = f"{published_at[:10]} {label}"
        add_node(
            nodes,
            news_id,
            label,
            "NewsArticle",
            {"iri": news_id, "publishedAt": published_at, "title": title},
        )
        add_edge(edges, "kg:news", news_id, "hasNews")


def add_optional_relationships(
    store: Store,
    nodes: dict[str, dict],
    edges: dict[str, dict],
    max_relationships: int,
) -> None:
    query = f"""
PREFIX ex: <https://stockgraph.local/kg/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?source ?predicate ?target ?sourceLabel ?targetLabel ?targetType
WHERE {{
  VALUES ?predicate {{
    ex:holds
    ex:belongsToConcept
    ex:memberOf
    ex:publishedAnnouncement
    ex:correlatedWith
  }}
  ?source ?predicate ?target .
  OPTIONAL {{ ?source rdfs:label ?sourceLabel }}
  OPTIONAL {{ ?target rdfs:label ?targetLabel }}
  OPTIONAL {{ ?target a ?targetType }}
}}
LIMIT {int(max_relationships)}
"""
    for row in store.query(query, prefixes=PREFIXES, use_default_graph_as_union=True):
        source = term_text(row["source"])
        target = term_text(row["target"])
        predicate = iri_tail(term_text(row["predicate"]))
        target_type = iri_tail(term_text(row["targetType"])) if row["targetType"] else "Correlation"
        source_label = clean_literal(row["sourceLabel"]) or iri_tail(source)
        target_label = clean_literal(row["targetLabel"]) or iri_tail(target)
        add_node(nodes, source, source_label, guess_type(source, "Stock"), {"iri": source})
        add_node(nodes, target, target_label, target_type, {"iri": target})
        add_edge(edges, source, target, predicate)


def add_node(nodes: dict[str, dict], node_id: str, label: str, node_type: str, meta: dict | None = None) -> None:
    if node_id in nodes:
        return
    style = NODE_STYLES.get(node_type, NODE_STYLES["Correlation"])
    nodes[node_id] = {
        "id": node_id,
        "data": {
            "label": compact_label(label, 48),
            "type": node_type,
            "meta": meta or {},
        },
        "style": {
            "size": style["size"],
            "fill": style["fill"],
            "stroke": style["stroke"],
            "lineWidth": 2,
            "labelText": compact_label(label, 42),
            "labelFill": "#111827",
            "labelFontSize": 11,
            "labelPlacement": "bottom",
        },
    }


def add_edge(edges: dict[str, dict], source: str, target: str, relation: str) -> None:
    edge_id = f"{source}|{relation}|{target}"
    if edge_id in edges:
        return
    style = EDGE_STYLES.get(relation, {"stroke": "#94a3b8", "lineWidth": 1.2})
    edges[edge_id] = {
        "id": edge_id,
        "source": source,
        "target": target,
        "data": {
            "relation": relation,
            "label": RELATION_LABELS.get(relation, relation),
        },
        "style": {
            "stroke": style["stroke"],
            "lineWidth": style["lineWidth"],
            "labelText": RELATION_LABELS.get(relation, ""),
            "labelFill": "#475569",
            "labelFontSize": 9,
            "endArrow": True,
        },
    }


def count_by_type(nodes) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        counts[node["data"]["type"]] += 1
    return dict(sorted(counts.items()))


def term_text(term) -> str:
    if term is None:
        return ""
    return getattr(term, "value", str(term).strip("<>"))


def clean_literal(term) -> str:
    if term is None:
        return ""
    return str(getattr(term, "value", term)).strip()


def iri_tail(value: str) -> str:
    if not value:
        return ""
    return unquote(value.rstrip("/").rsplit("/", 1)[-1])


def compact_label(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def guess_type(iri: str, fallback: str) -> str:
    if "/stock/" in iri:
        return "Stock"
    if "/concept/" in iri:
        return "Concept"
    if "/shareholder/" in iri:
        return "Shareholder"
    if "/market-connect/" in iri:
        return "MarketConnect"
    return fallback


def render_html(graph: dict) -> str:
    graph_json = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Financial KG - AntV G6</title>
  <script src="https://unpkg.com/@antv/g6@5/dist/g6.min.js"></script>
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.js"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f8fafc;
      --panel: #ffffff;
      --line: #dbe3ef;
      --text: #111827;
      --muted: #64748b;
      --accent: #2563eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      height: 100vh;
      overflow: hidden;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}
    .app {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      grid-template-rows: 56px minmax(0, 1fr);
      height: 100vh;
    }}
    header {{
      grid-column: 1 / -1;
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 0 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      min-width: 0;
    }}
    h1 {{
      margin: 0;
      font-size: 15px;
      line-height: 1.2;
      font-weight: 700;
      white-space: nowrap;
    }}
    .meta {{
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .toolbar {{
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }}
    .search {{
      width: min(320px, 32vw);
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      font-size: 13px;
      outline: none;
      background: #fff;
    }}
    .search:focus {{ border-color: var(--accent); }}
    button {{
      width: 34px;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }}
    button:hover {{ border-color: #94a3b8; }}
    button svg {{ width: 17px; height: 17px; }}
    #graph {{
      min-width: 0;
      min-height: 0;
      background: #f8fafc;
    }}
    aside {{
      min-width: 0;
      border-left: 1px solid var(--line);
      background: var(--panel);
      overflow: auto;
    }}
    .section {{
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }}
    .section h2 {{
      margin: 0 0 10px;
      font-size: 12px;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 700;
    }}
    .stats {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }}
    .stat {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #f8fafc;
    }}
    .stat strong {{
      display: block;
      font-size: 18px;
      line-height: 1.1;
    }}
    .stat span {{
      color: var(--muted);
      font-size: 12px;
    }}
    .filters {{
      display: grid;
      gap: 8px;
    }}
    label.check {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: #334155;
    }}
    input[type="checkbox"] {{ width: 15px; height: 15px; }}
    .swatch {{
      width: 10px;
      height: 10px;
      border-radius: 999px;
      flex: 0 0 auto;
    }}
    .details {{
      display: grid;
      gap: 8px;
      font-size: 13px;
      line-height: 1.45;
    }}
    .detail-title {{
      font-weight: 700;
      overflow-wrap: anywhere;
    }}
    .detail-row {{
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      gap: 8px;
      color: #334155;
    }}
    .detail-row span:first-child {{ color: var(--muted); }}
    .detail-row span:last-child {{ overflow-wrap: anywhere; }}
    .error {{
      padding: 20px;
      color: #991b1b;
      font-size: 14px;
    }}
    @media (max-width: 860px) {{
      .app {{
        grid-template-columns: 1fr;
        grid-template-rows: 56px minmax(0, 1fr) 260px;
      }}
      aside {{
        border-left: 0;
        border-top: 1px solid var(--line);
      }}
      .search {{ width: 42vw; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <header>
      <h1>Financial KG</h1>
      <div class="meta" id="meta"></div>
      <div class="toolbar">
        <input class="search" id="search" type="search" placeholder="Search" />
        <button id="reset" title="Reset"><i data-lucide="rotate-ccw"></i></button>
      </div>
    </header>
    <main id="graph"></main>
    <aside>
      <section class="section">
        <h2>Stats</h2>
        <div class="stats">
          <div class="stat"><strong id="node-count">0</strong><span>Nodes</span></div>
          <div class="stat"><strong id="edge-count">0</strong><span>Edges</span></div>
        </div>
      </section>
      <section class="section">
        <h2>Types</h2>
        <div class="filters" id="filters"></div>
      </section>
      <section class="section">
        <h2>Details</h2>
        <div class="details" id="details">
          <div class="detail-title">No selection</div>
        </div>
      </section>
    </aside>
  </div>
  <script id="graph-data" type="application/json">{graph_json}</script>
  <script>
    const payload = JSON.parse(document.getElementById('graph-data').textContent);
    const rawData = {{ nodes: payload.nodes, edges: payload.edges }};
    const typeStyles = {json.dumps(NODE_STYLES, ensure_ascii=False)};
    let activeTypes = new Set(Object.keys(payload.stats.byType));
    let graph = null;
    let currentData = rawData;

    document.getElementById('meta').textContent =
      `${{payload.generatedAt}} - ${{payload.stats.nodes}} nodes - ${{payload.stats.edges}} edges`;

    if (window.lucide) window.lucide.createIcons();
    setupFilters();
    applyFilters();

    document.getElementById('search').addEventListener('input', applyFilters);
    document.getElementById('reset').addEventListener('click', () => {{
      document.getElementById('search').value = '';
      activeTypes = new Set(Object.keys(payload.stats.byType));
      document.querySelectorAll('#filters input').forEach((input) => input.checked = true);
      applyFilters();
    }});
    window.addEventListener('resize', () => renderGraph(currentData));

    function setupFilters() {{
      const root = document.getElementById('filters');
      root.innerHTML = '';
      Object.entries(payload.stats.byType).forEach(([type, count]) => {{
        const style = typeStyles[type] || typeStyles.Correlation;
        const id = `filter-${{type}}`;
        const row = document.createElement('label');
        row.className = 'check';
        row.innerHTML = `
          <input id="${{id}}" type="checkbox" checked />
          <span class="swatch" style="background:${{style.fill}}"></span>
          <span>${{type}} - ${{count}}</span>
        `;
        row.querySelector('input').addEventListener('change', (event) => {{
          if (event.target.checked) activeTypes.add(type);
          else activeTypes.delete(type);
          applyFilters();
        }});
        root.appendChild(row);
      }});
    }}

    function applyFilters() {{
      const term = document.getElementById('search').value.trim().toLowerCase();
      let nodes = rawData.nodes.filter((node) => activeTypes.has(node.data.type));
      const activeIds = new Set(nodes.map((node) => node.id));
      if (term) {{
        const matched = new Set();
        nodes.forEach((node) => {{
          const text = JSON.stringify(node.data).toLowerCase();
          if (text.includes(term)) matched.add(node.id);
        }});
        rawData.edges.forEach((edge) => {{
          if (matched.has(edge.source)) matched.add(edge.target);
          if (matched.has(edge.target)) matched.add(edge.source);
        }});
        nodes = nodes.filter((node) => matched.has(node.id));
      }}
      const ids = new Set(nodes.map((node) => node.id));
      const edges = rawData.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
      currentData = {{ nodes, edges }};
      renderGraph(currentData);
      document.getElementById('node-count').textContent = nodes.length;
      document.getElementById('edge-count').textContent = edges.length;
    }}

    function renderGraph(data) {{
      const container = document.getElementById('graph');
      if (!window.G6 || !window.G6.Graph) {{
        container.innerHTML = '<div class="error">AntV G6 failed to load.</div>';
        return;
      }}
      if (graph && graph.destroy) graph.destroy();
      container.innerHTML = '';
      const width = Math.max(container.clientWidth, 320);
      const height = Math.max(container.clientHeight, 320);
      graph = new window.G6.Graph({{
        container,
        width,
        height,
        autoFit: 'view',
        data,
        layout: {{
          type: 'force',
          preventOverlap: true,
          nodeSpacing: 18,
          linkDistance: 90,
        }},
        node: {{
          style: {{
            labelFill: '#111827',
            labelFontSize: 11,
            labelPlacement: 'bottom',
          }},
        }},
        edge: {{
          style: {{
            opacity: 0.74,
          }},
        }},
        behaviors: [
          'zoom-canvas',
          'drag-canvas',
          'drag-element-force',
          {{ type: 'auto-adapt-label', throttle: 160, padding: 4 }},
        ],
        plugins: [{{ type: 'grid-line', size: 40 }}],
        animation: false,
      }});
      graph.render();
      attachEvents();
    }}

    function attachEvents() {{
      if (!graph || !graph.on) return;
      graph.on('node:click', (event) => {{
        const id =
          event?.item?.getModel?.()?.id ||
          event?.target?.id ||
          event?.target?.attributes?.id ||
          event?.target?.get?.('id');
        const node = currentData.nodes.find((item) => item.id === id);
        if (node) showDetails(node);
      }});
    }}

    function showDetails(node) {{
      const meta = node.data.meta || {{}};
      const rows = [
        ['Type', node.data.type],
        ['ID', node.id],
        ...Object.entries(meta).filter(([, value]) => value !== null && value !== undefined && value !== ''),
      ];
      document.getElementById('details').innerHTML = `
        <div class="detail-title">${{escapeHtml(node.data.label)}}</div>
        ${{rows.map(([key, value]) => `
          <div class="detail-row">
            <span>${{escapeHtml(key)}}</span>
            <span>${{escapeHtml(String(value))}}</span>
          </div>
        `).join('')}}
      `;
    }}

    function escapeHtml(value) {{
      return value.replace(/[&<>"']/g, (char) => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
      }}[char]));
    }}
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
