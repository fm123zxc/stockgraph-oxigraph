"""Build an Oxigraph RDF store from the original notebook data files."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import math
import pandas as pd
from pyoxigraph import Literal, NamedNode, Quad, Store

from .vocab import ex, rdf, rdfs, schema, xsd


@dataclass
class BuildStats:
    """Counters returned by a graph build."""

    rows: dict[str, int] = field(default_factory=dict)
    quads: int = 0
    skipped_files: list[str] = field(default_factory=list)

    def add_rows(self, name: str, count: int) -> None:
        self.rows[name] = self.rows.get(name, 0) + count


class QuadWriter:
    """Small buffered writer around Oxigraph's bulk insertion API."""

    def __init__(self, store: Store, stats: BuildStats, graph: NamedNode, chunk_size: int) -> None:
        self.store = store
        self.stats = stats
        self.graph = graph
        self.chunk_size = chunk_size
        self._buffer: list[Quad] = []

    def add(self, subject: NamedNode, predicate: NamedNode, obj) -> None:
        self._buffer.append(Quad(subject, predicate, obj, self.graph))
        if len(self._buffer) >= self.chunk_size:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        self.store.bulk_extend(self._buffer)
        self.stats.quads += len(self._buffer)
        self._buffer.clear()


def build_store(
    source_dir: Path,
    store_path: Path,
    *,
    graph_iri: str = "https://stockgraph.local/kg/graph/main",
    clear: bool = False,
    max_price_rows: int | None = None,
    max_news_rows: int | None = None,
    chunk_size: int = 10_000,
) -> BuildStats:
    """Build or update an Oxigraph store from CSV files.

    The source directory should point to the original
    ``Financial-Knowledge-Graphs`` checkout. Files missing from the notebook
    workflow are skipped so the builder can run against the small sample data
    included in this workspace.
    """

    source_dir = source_dir.resolve()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(store_path))
    if clear:
        store.clear()

    stats = BuildStats()
    writer = QuadWriter(store, stats, NamedNode(graph_iri), chunk_size)

    add_schema(writer)
    add_stock_price_files(writer, stats, source_dir / "data", max_price_rows=max_price_rows)
    add_news(writer, stats, source_dir / "data" / "latest_news.csv", max_rows=max_news_rows)
    add_optional_neo4j_csvs(writer, stats, source_dir)

    writer.flush()
    store.flush()
    return stats


def add_schema(writer: QuadWriter) -> None:
    classes = {
        "Stock": "股票",
        "TradingDay": "交易日行情",
        "NewsArticle": "财经新闻",
        "Shareholder": "股东",
        "Concept": "概念",
        "MarketConnect": "沪深股通",
        "Announcement": "公告",
    }
    predicates = {
        "hasTradingDay": "有交易日行情",
        "hasNews": "包含新闻",
        "holds": "参股",
        "belongsToConcept": "概念属于",
        "publishedAnnouncement": "发布公告",
        "memberOf": "成分股属于",
        "correlatedWith": "收益率相关",
    }
    for name, label in classes.items():
        subject = ex(name)
        writer.add(subject, rdf("type"), rdfs("Class"))
        writer.add(subject, rdfs("label"), Literal(label, language="zh"))
    for name, label in predicates.items():
        subject = ex(name)
        writer.add(subject, rdf("type"), rdf("Property"))
        writer.add(subject, rdfs("label"), Literal(label, language="zh"))


def add_stock_price_files(
    writer: QuadWriter,
    stats: BuildStats,
    data_dir: Path,
    *,
    max_price_rows: int | None,
) -> None:
    paths = sorted(data_dir.glob("*.XSHE.csv")) + sorted(data_dir.glob("*.XSHG.csv"))
    if not paths:
        stats.skipped_files.append(str(data_dir / "*.XSHE.csv"))
        return

    for path in paths:
        code = path.stem
        stock = stock_node(code)
        writer.add(stock, rdf("type"), ex("Stock"))
        writer.add(stock, rdfs("label"), Literal(code))
        writer.add(stock, ex("securityCode"), Literal(code))
        writer.add(stock, ex("exchange"), Literal(code.split(".")[-1]))

        count = 0
        for chunk in pd.read_csv(path, chunksize=chunk_size_for(max_price_rows)):
            if max_price_rows is not None:
                chunk = chunk.head(max(0, max_price_rows - count))
            for _, row in chunk.iterrows():
                if not has_value(row.get("trade_date")):
                    continue
                day_id = normalize_date_id(row["trade_date"])
                day = trading_day_node(code, day_id)
                writer.add(day, rdf("type"), ex("TradingDay"))
                writer.add(day, ex("ofStock"), stock)
                writer.add(stock, ex("hasTradingDay"), day)
                writer.add(day, ex("tradeDate"), typed_literal(day_id, "date"))
                for column in price_columns(chunk.columns):
                    add_property(writer, day, column, row.get(column))
                count += 1
                if max_price_rows is not None and count >= max_price_rows:
                    break
            if max_price_rows is not None and count >= max_price_rows:
                break
        stats.add_rows(path.name, count)


def add_news(writer: QuadWriter, stats: BuildStats, path: Path, *, max_rows: int | None) -> None:
    if not path.exists():
        stats.skipped_files.append(str(path))
        return

    count = 0
    for chunk in pd.read_csv(path, chunksize=chunk_size_for(max_rows)):
        if max_rows is not None:
            chunk = chunk.head(max(0, max_rows - count))
        for index, row in chunk.iterrows():
            content = clean_text(row.get("content"))
            title = clean_text(row.get("title"))
            timestamp = clean_text(row.get("datetime"))
            if not content and not title:
                continue
            news = news_node(timestamp, index)
            writer.add(news, rdf("type"), ex("NewsArticle"))
            writer.add(news, rdfs("label"), Literal(title or content[:80]))
            if title:
                writer.add(news, schema("headline"), Literal(title))
            if content:
                writer.add(news, schema("articleBody"), Literal(content))
            if timestamp:
                writer.add(news, schema("datePublished"), date_time_literal(timestamp))
            count += 1
            if max_rows is not None and count >= max_rows:
                break
        if max_rows is not None and count >= max_rows:
            break
    stats.add_rows(path.name, count)


def add_optional_neo4j_csvs(writer: QuadWriter, stats: BuildStats, source_dir: Path) -> None:
    financial_data = source_dir / "financial_data"
    add_stock_basic(writer, stats, first_existing(source_dir, [
        "financial_data/stock_basic.csv",
        "stock_basic.csv",
    ]))
    add_holders(writer, stats, first_existing(source_dir, [
        "financial_data/stock_holders.csv",
        "financial_data/holders.csv",
        "holders.csv",
    ]))
    add_concepts(writer, stats, first_existing(source_dir, [
        "financial_data/concept.csv",
        "concept.csv",
    ]))
    add_stock_concepts(writer, stats, first_existing(source_dir, [
        "financial_data/stock_concept.csv",
        "stock_concept.csv",
    ]))
    add_market_connect(writer, stats, "SH", first_existing(source_dir, [
        "financial_data/sh.csv",
        "sh.csv",
    ]))
    add_market_connect(writer, stats, "SZ", first_existing(source_dir, [
        "financial_data/sz.csv",
        "sz.csv",
    ]))
    add_correlations(writer, stats, first_existing(source_dir, [
        "financial_data/corr.csv",
        "corr.csv",
    ]))
    add_notices(writer, stats, financial_data / "notices")


def add_stock_basic(writer: QuadWriter, stats: BuildStats, path: Path | None) -> None:
    if path is None:
        stats.skipped_files.append("stock_basic.csv")
        return
    frame = read_csv_flexible(path)
    code_col = find_column(frame, ["TS代码", "TS代码", "ts_code"])
    symbol_col = find_column(frame, ["股票代码", "symbol"])
    name_col = find_column(frame, ["股票名称", "name"])
    industry_col = find_column(frame, ["行业", "industry"])
    count = 0
    for _, row in frame.iterrows():
        code = clean_text(row.get(code_col))
        if not code:
            continue
        stock = stock_node(code)
        writer.add(stock, rdf("type"), ex("Stock"))
        writer.add(stock, ex("tsCode"), Literal(code))
        if symbol_col:
            add_property(writer, stock, "symbol", row.get(symbol_col))
        if name_col:
            add_property(writer, stock, "name", row.get(name_col))
            name = clean_text(row.get(name_col))
            if name:
                writer.add(stock, rdfs("label"), Literal(name, language="zh"))
        if industry_col:
            add_property(writer, stock, "industry", row.get(industry_col))
        count += 1
    stats.add_rows(path.name, count)


def add_holders(writer: QuadWriter, stats: BuildStats, path: Path | None) -> None:
    if path is None:
        stats.skipped_files.append("holders.csv")
        return
    frame = read_csv_flexible(path).drop_duplicates()
    code_col = find_column(frame, ["ts_code", "TS代码", "TS代码"])
    name_col = find_column(frame, ["holder_name", "股东名称"])
    amount_col = find_column(frame, ["hold_amount", "持股数量"])
    ratio_col = find_column(frame, ["hold_ratio", "持股比例"])
    count = 0
    for index, row in frame.iterrows():
        code = clean_text(row.get(code_col))
        holder_name = clean_text(row.get(name_col))
        if not code or not holder_name:
            continue
        stock = stock_node(code)
        holder = holder_node(holder_name, index)
        writer.add(holder, rdf("type"), ex("Shareholder"))
        writer.add(holder, rdfs("label"), Literal(holder_name, language="zh"))
        writer.add(holder, ex("holderName"), Literal(holder_name))
        if amount_col:
            add_property(writer, holder, "holdAmount", row.get(amount_col))
        if ratio_col:
            add_property(writer, holder, "holdRatio", row.get(ratio_col))
        writer.add(holder, ex("holds"), stock)
        count += 1
    stats.add_rows(path.name, count)


def add_concepts(writer: QuadWriter, stats: BuildStats, path: Path | None) -> None:
    if path is None:
        stats.skipped_files.append("concept.csv")
        return
    frame = read_csv_flexible(path)
    id_col = find_column(frame, ["code", "id", "概念代码"])
    name_col = find_column(frame, ["name", "concept_name", "概念名称"])
    count = 0
    for index, row in frame.iterrows():
        concept_id = clean_text(row.get(id_col)) or f"concept-{index}"
        concept = concept_node(concept_id)
        writer.add(concept, rdf("type"), ex("Concept"))
        writer.add(concept, ex("conceptCode"), Literal(concept_id))
        if name_col:
            name = clean_text(row.get(name_col))
            if name:
                writer.add(concept, rdfs("label"), Literal(name, language="zh"))
                writer.add(concept, ex("conceptName"), Literal(name))
        count += 1
    stats.add_rows(path.name, count)


def add_stock_concepts(writer: QuadWriter, stats: BuildStats, path: Path | None) -> None:
    if path is None:
        stats.skipped_files.append("stock_concept.csv")
        return
    frame = read_csv_flexible(path)
    concept_col = find_column(frame, ["id", "concept_code", "概念代码"])
    stock_col = find_column(frame, ["ts_code", "TS代码", "TS代码"])
    count = 0
    for _, row in frame.iterrows():
        concept_id = clean_text(row.get(concept_col))
        code = clean_text(row.get(stock_col))
        if not code or not concept_id:
            continue
        writer.add(stock_node(code), ex("belongsToConcept"), concept_node(concept_id))
        count += 1
    stats.add_rows(path.name, count)


def add_market_connect(writer: QuadWriter, stats: BuildStats, market: str, path: Path | None) -> None:
    if path is None:
        stats.skipped_files.append(f"{market.lower()}.csv")
        return
    frame = read_csv_flexible(path)
    code_col = find_column(frame, ["ts_code", "TS代码", "TS代码"])
    market_node_ref = market_connect_node(market)
    writer.add(market_node_ref, rdf("type"), ex("MarketConnect"))
    writer.add(market_node_ref, rdfs("label"), Literal("沪股通" if market == "SH" else "深股通", language="zh"))
    count = 0
    for _, row in frame.iterrows():
        code = clean_text(row.get(code_col))
        if not code:
            continue
        writer.add(stock_node(code), ex("memberOf"), market_node_ref)
        count += 1
    stats.add_rows(path.name, count)


def add_correlations(writer: QuadWriter, stats: BuildStats, path: Path | None) -> None:
    if path is None:
        stats.skipped_files.append("corr.csv")
        return
    frame = read_csv_flexible(path)
    columns = list(frame.columns)
    left_col = find_column(frame, ["stock_a", "left", "source", "股票A"]) or (columns[1] if len(columns) > 1 else None)
    right_col = find_column(frame, ["stock_b", "right", "target", "股票B"]) or (columns[2] if len(columns) > 2 else None)
    value_col = find_column(frame, ["corr", "correlation", "相关系数"]) or (columns[3] if len(columns) > 3 else None)
    count = 0
    for _, row in frame.iterrows():
        left = clean_stock_code(row.get(left_col))
        right = clean_stock_code(row.get(right_col))
        if not left or not right:
            continue
        relation = correlation_node(left, right)
        writer.add(relation, rdf("type"), ex("StockCorrelation"))
        writer.add(relation, ex("sourceStock"), stock_node(left))
        writer.add(relation, ex("targetStock"), stock_node(right))
        writer.add(stock_node(left), ex("correlatedWith"), stock_node(right))
        if value_col:
            add_property(writer, relation, "correlation", row.get(value_col))
        count += 1
    stats.add_rows(path.name, count)


def add_notices(writer: QuadWriter, stats: BuildStats, notices_dir: Path) -> None:
    if not notices_dir.exists():
        stats.skipped_files.append(str(notices_dir))
        return
    count = 0
    for path in sorted(notices_dir.glob("*.csv")):
        frame = read_csv_flexible(path)
        code_col = find_column(frame, ["ts_code", "TS代码", "TS代码"]) or (frame.columns[0] if len(frame.columns) else None)
        date_col = find_column(frame, ["ann_date", "date", "日期"]) or (frame.columns[1] if len(frame.columns) > 1 else None)
        title_col = find_column(frame, ["title", "标题"]) or (frame.columns[2] if len(frame.columns) > 2 else None)
        content_col = find_column(frame, ["content", "内容"]) or (frame.columns[3] if len(frame.columns) > 3 else None)
        for index, row in frame.iterrows():
            code = clean_text(row.get(code_col))
            title = clean_text(row.get(title_col))
            content = clean_text(row.get(content_col))
            if not code or not (title or content):
                continue
            notice = announcement_node(code, row.get(date_col), index)
            writer.add(notice, rdf("type"), ex("Announcement"))
            writer.add(notice, rdfs("label"), Literal(title or content[:80], language="zh"))
            if title:
                writer.add(notice, schema("headline"), Literal(title))
            if content:
                writer.add(notice, schema("articleBody"), Literal(content))
            if date_col:
                add_property(writer, notice, "announcementDate", row.get(date_col))
            writer.add(stock_node(code), ex("publishedAnnouncement"), notice)
            count += 1
    stats.add_rows("notices/*.csv", count)


def add_property(writer: QuadWriter, subject: NamedNode, name: str, value) -> None:
    if not has_value(value):
        return
    writer.add(subject, ex(to_camel_case(name)), literal_from_value(value))


def literal_from_value(value) -> Literal:
    if isinstance(value, bool):
        return Literal(value)
    if isinstance(value, int):
        return Literal(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return Literal(str(value))
        return Literal(value)
    text = clean_text(value)
    if text is None:
        return Literal("")
    return Literal(text)


def typed_literal(value: str, datatype: str) -> Literal:
    return Literal(value, datatype=xsd(datatype))


def date_time_literal(value: str) -> Literal:
    text = clean_text(value)
    if not text:
        return Literal("")
    try:
        parsed = datetime.fromisoformat(text)
        return Literal(parsed.isoformat(sep="T"), datatype=xsd("dateTime"))
    except ValueError:
        return Literal(text)


def read_csv_flexible(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def first_existing(root: Path, candidates: Iterable[str]) -> Path | None:
    for candidate in candidates:
        path = root / candidate
        if path.exists():
            return path
    return None


def find_column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    normalized = {normalize_col(column): column for column in frame.columns}
    for candidate in candidates:
        match = normalized.get(normalize_col(candidate))
        if match:
            return match
    return None


def normalize_col(value: str) -> str:
    return str(value).strip().lower().replace("_", "").replace(" ", "")


def price_columns(columns: Iterable[str]) -> list[str]:
    excluded = {"trade_date"}
    return [column for column in columns if column not in excluded and not str(column).startswith("Unnamed")]


def chunk_size_for(limit: int | None) -> int:
    if limit is None:
        return 10_000
    return max(1, min(10_000, limit))


def has_value(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass
    if isinstance(value, str) and not value.strip():
        return False
    return True


def clean_text(value) -> str | None:
    if not has_value(value):
        return None
    return str(value).strip()


def clean_stock_code(value) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    return text.rstrip(".").strip()


def safe_segment(value) -> str:
    return quote(str(value).strip().replace("/", "_"), safe="")


def normalize_date_id(value) -> str:
    text = clean_text(value) or ""
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def to_camel_case(name: str) -> str:
    text = str(name).strip()
    if not text:
        return "value"
    replacements = {
        "TS代码": "tsCode",
        "股票代码": "symbol",
        "股票名称": "name",
        "行业": "industry",
        "持股数量": "holdAmount",
        "持股比例": "holdRatio",
        "日期": "date",
        "标题": "title",
        "内容": "content",
    }
    if text in replacements:
        return replacements[text]
    parts = text.replace("-", "_").replace(" ", "_").split("_")
    if len(parts) == 1:
        return parts[0]
    return parts[0].lower() + "".join(part[:1].upper() + part[1:] for part in parts[1:] if part)


def stock_node(code: str) -> NamedNode:
    return ex(f"stock/{safe_segment(code)}")


def trading_day_node(code: str, day: str) -> NamedNode:
    return ex(f"stock/{safe_segment(code)}/day/{safe_segment(day)}")


def news_node(timestamp: str | None, index: int) -> NamedNode:
    key = timestamp or f"row-{index}"
    return ex(f"news/{safe_segment(key)}")


def holder_node(name: str, index: int) -> NamedNode:
    return ex(f"shareholder/{safe_segment(name)}-{index}")


def concept_node(concept_id: str) -> NamedNode:
    return ex(f"concept/{safe_segment(concept_id)}")


def market_connect_node(market: str) -> NamedNode:
    return ex(f"market-connect/{safe_segment(market)}")


def correlation_node(left: str, right: str) -> NamedNode:
    return ex(f"correlation/{safe_segment(left)}/{safe_segment(right)}")


def announcement_node(code: str, date_value, index: int) -> NamedNode:
    date_key = clean_text(date_value) or f"row-{index}"
    return ex(f"stock/{safe_segment(code)}/announcement/{safe_segment(date_key)}")
