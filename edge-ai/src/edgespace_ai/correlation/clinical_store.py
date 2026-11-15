"""SQLite FTS5 (BM25, mode=ro, busy_timeout=5000) clinical store with YAML fallback."""

from __future__ import annotations

import re
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from ..utils.logging import get_logger

logger = get_logger("edgespace_ai.correlation.clinical_store")


@dataclass(frozen=True)
class ClinicalDocument:
    """Clinical guideline/protocol hit returned by SQLite FTS5 or YAML fallback."""

    doc_id: str
    title: str
    subsystem: str
    snippet: str
    score: float
    source: str  # "sqlite_fts5" | "yaml_fallback"
    source_id: str = ""


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file using PyYAML when installed, or a built-in pure-Python YAML parser."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        import yaml  # type: ignore[import-untyped]

        parsed = yaml.safe_load(text)
        return parsed if isinstance(parsed, dict) else {}
    except ImportError:
        return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Minimal indentation-based YAML parser supporting dicts, lists, and scalar types."""
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, stripped))

    if not lines:
        return {}
    value, _ = _parse_yaml_block(lines, 0, lines[0][0])
    return value if isinstance(value, dict) else {}


def _parse_yaml_block(lines: list[tuple[int, str]], idx: int, base_indent: int) -> tuple[Any, int]:
    if idx >= len(lines):
        return {}, idx

    if lines[idx][1].startswith("- "):
        items: list[Any] = []
        while idx < len(lines) and lines[idx][0] == base_indent and lines[idx][1].startswith("- "):
            item_text = lines[idx][1][2:].strip()
            idx += 1
            if ":" in item_text and not _is_quoted(item_text):
                k, v_str = _split_kv(item_text)
                obj: dict[str, Any] = {}
                if v_str == "":
                    if idx < len(lines) and lines[idx][0] > base_indent:
                        sub_val, idx = _parse_yaml_block(lines, idx, lines[idx][0])
                        obj[k] = sub_val
                    else:
                        obj[k] = None
                else:
                    obj[k] = _parse_yaml_scalar(v_str)
                if idx < len(lines) and lines[idx][0] > base_indent:
                    extra, idx = _parse_yaml_block(lines, idx, lines[idx][0])
                    if isinstance(extra, dict):
                        obj.update(extra)
                items.append(obj)
            elif item_text == "":
                if idx < len(lines) and lines[idx][0] > base_indent:
                    sub_val, idx = _parse_yaml_block(lines, idx, lines[idx][0])
                    items.append(sub_val)
                else:
                    items.append(None)
            else:
                items.append(_parse_yaml_scalar(item_text))
        return items, idx

    mapping: dict[str, Any] = {}
    while idx < len(lines) and lines[idx][0] == base_indent:
        line_text = lines[idx][1]
        if line_text.startswith("- "):
            break
        k, v_str = _split_kv(line_text)
        idx += 1
        if v_str == "":
            if idx < len(lines) and lines[idx][0] > base_indent:
                sub_val, idx = _parse_yaml_block(lines, idx, lines[idx][0])
                mapping[k] = sub_val
            else:
                mapping[k] = None
        else:
            mapping[k] = _parse_yaml_scalar(v_str)
    return mapping, idx


def _is_quoted(s: str) -> bool:
    return (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'"))


def _split_kv(s: str) -> tuple[str, str]:
    in_quotes: Optional[str] = None
    for i, ch in enumerate(s):
        if ch in ('"', "'"):
            if in_quotes is None:
                in_quotes = ch
            elif in_quotes == ch:
                in_quotes = None
        elif ch == ":" and in_quotes is None:
            key = s[:i].strip().strip('"').strip("'")
            val = s[i + 1 :].strip()
            return key, val
    return s.strip(), ""


def _parse_yaml_scalar(raw: str) -> Any:
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(part.strip()) for part in inner.split(",")]
    if _is_quoted(s):
        return s[1:-1]
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


DEFAULT_DB_PATH = Path("../data/edgespace.db")
DEFAULT_DB_CANDIDATES: tuple[Path, ...] = (
    DEFAULT_DB_PATH,
    Path("var/edgespace.db"),
    Path("../var/edgespace.db"),
)


def resolve_db_path(db_path: Optional[Path | str] = None) -> Path:
    """Resolve SQLite path, falling back from ../data/edgespace.db to var/edgespace.db."""
    if db_path is not None:
        candidate = Path(db_path)
        if candidate != DEFAULT_DB_PATH or candidate.is_file():
            return candidate
    for path in DEFAULT_DB_CANDIDATES:
        if path.is_file():
            return path
    return Path("../var/edgespace.db") if Path("../var").is_dir() else Path("var/edgespace.db")


class ClinicalStore:
    """Queries SQLite FTS5 (BM25) in read-only mode with YAML fallback."""

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        knowledge_base_path: Optional[Path | str] = None,
    ) -> None:
        self._explicit_db_path = db_path is not None and Path(db_path) != DEFAULT_DB_PATH
        self.db_path = resolve_db_path(db_path)
        default_kb = Path(__file__).resolve().parents[3] / "knowledge-base" / "nasa_causal_graph.yaml"
        self.knowledge_base_path = Path(knowledge_base_path) if knowledge_base_path else default_kb
        self._yaml_cache: Optional[dict[str, Any]] = None

    def search(self, query: str, *, concepts: Sequence[str] = (), limit: int = 5) -> list[ClinicalDocument]:
        """Search clinical protocols via SQLite FTS5 BM25 (mode=ro), falling back to YAML."""
        terms = self._build_search_terms(query, concepts)
        if not terms:
            return []

        fts_hits = self._search_sqlite_fts5(terms, limit=limit)
        if fts_hits:
            return fts_hits
        return [] if self._explicit_db_path else self._search_yaml_fallback(terms, limit=limit)

    def _search_sqlite_fts5(self, terms: Sequence[str], *, limit: int) -> list[ClinicalDocument]:
        if not self.db_path.is_file() and not self._explicit_db_path:
            self.db_path = resolve_db_path(None)
        if not self.db_path.is_file():
            return []

        uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            conn.execute("PRAGMA busy_timeout = 5000;")

            fts_tables = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND lower(sql) LIKE '%fts5%'"
            ).fetchall()
            if not fts_tables:
                return []

            match_expr = " OR ".join(f'"{t}"' for t in terms[:12])
            results: list[ClinicalDocument] = []

            for table_name, _ in fts_tables:
                cols_info = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
                col_names = [row[1] for row in cols_info]
                if not col_names:
                    continue

                sql = (
                    f'SELECT rowid, bm25("{table_name}") AS score, * '
                    f'FROM "{table_name}" WHERE "{table_name}" MATCH ? '
                    f"ORDER BY score LIMIT ?"
                )
                try:
                    rows = conn.execute(sql, (match_expr, limit)).fetchall()
                except sqlite3.OperationalError:
                    continue

                for row in rows:
                    rowid = row[0]
                    bm25_score = float(row[1])
                    col_values = dict(zip(col_names, row[2:]))
                    doc_id = str(
                        col_values.get("protocol_id")
                        or col_values.get("report_id")
                        or col_values.get("id")
                        or col_values.get("source_id")
                        or f"{table_name}:{rowid}"
                    )
                    title = str(col_values.get("name") or col_values.get("title") or doc_id)
                    subsystem = str(col_values.get("subsystem") or col_values.get("subsystems") or "")
                    snippet = str(
                        col_values.get("description")
                        or col_values.get("problem")
                        or col_values.get("content_text")
                        or col_values.get("content")
                        or col_values.get("steps")
                        or title
                    )
                    source_id=str(col_values.get('source_id') or '')
                    if col_values.get('report_id'):
                        ref=conn.execute('SELECT source_id,payload_json,category FROM clinical_reports WHERE report_id=?',(doc_id,)).fetchone()
                        if ref:
                            if ref[2]=='HAZARD':continue
                            source_id=ref[0]
                    results.append(
                        ClinicalDocument(
                            doc_id=doc_id,
                            title=title,
                            subsystem=subsystem,
                            snippet=snippet[:280],
                            score=-bm25_score,  # lower bm25 is better match in SQLite FTS5
                            source="sqlite_fts5",source_id=source_id,
                        )
                    )
                if results:
                    break

            results.sort(key=lambda d: d.score, reverse=True)
            return results[:limit]
        except Exception as exc:
            if self._explicit_db_path: raise RuntimeError("SQLite clinical search failed") from exc
            logger.debug("sqlite fts5 query skipped/fallback", extra={"err": str(exc)})
            return []
        finally:
            if conn is not None:
                conn.close()

    def _search_yaml_fallback(self, terms: Sequence[str], *, limit: int) -> list[ClinicalDocument]:
        if self._yaml_cache is None:
            if not self.knowledge_base_path.is_file():
                return []
            self._yaml_cache = load_yaml_file(self.knowledge_base_path)

        conditions = self._yaml_cache.get("conditions", [])
        if not isinstance(conditions, list):
            return []

        scored: list[ClinicalDocument] = []
        term_set = {t.lower() for t in terms}

        for cond in conditions:
            if not isinstance(cond, dict):
                continue
            haystack = " ".join(
                [
                    str(cond.get("id", "")),
                    str(cond.get("name", "")),
                    str(cond.get("source_id", "")),
                    str(cond.get("subsystem", "")),
                    " ".join(str(k) for k in (cond.get("symptoms") or {}).keys()),
                    " ".join(str(c) for c in (cond.get("countermeasures") or [])),
                ]
            ).lower()

            hits = sum(1 for t in term_set if t in haystack)
            if hits > 0:
                scored.append(
                    ClinicalDocument(
                        doc_id=str(cond.get("source_id") or cond.get("id")),
                        title=str(cond.get("name") or cond.get("id")),
                        subsystem=str(cond.get("subsystem") or ""),
                        snippet="; ".join(str(c) for c in (cond.get("countermeasures") or [])[:2]),
                        score=float(hits),
                        source="yaml_fallback",
                    )
                )

        scored.sort(key=lambda d: d.score, reverse=True)
        return scored[:limit]

    _CONCEPT_SEARCH_EXPANSIONS: dict[str, tuple[str, ...]] = {
        "muscle_pain": ("muscular", "muscle", "fitness", "ared", "ossea", "bone"),
        "muscle_weakness": ("fraqueza", "weakness", "fitness", "muscular", "ared"),
        "limb_swelling": ("cardiovascular", "fluid", "edema", "dcs", "stasis"),
        "bone_pain": ("ossea", "bone", "renal", "ared"),
        "orthostatic_intolerance": ("ortostatica", "orthostatic", "fluid", "cardiovascular"),
        "joint_pain": ("articular", "joint", "dcs", "iron"),
        "abdominal_pain": ("abdominal", "gi", "nutrition", "microbiome"),
    }

    @classmethod
    def _build_search_terms(cls, query: str, concepts: Sequence[str]) -> list[str]:
        tokens = re.findall(r"\w{3,}", query.lower())
        expanded: list[str] = []
        for c in concepts:
            clean_c = c.strip().lower()
            if clean_c:
                expanded.append(clean_c)
                expanded.extend(clean_c.split("_"))
                expanded.extend(cls._CONCEPT_SEARCH_EXPANSIONS.get(clean_c, ()))
        merged: list[str] = []
        seen: set[str] = set()
        for item in [*expanded, *tokens]:
            clean = item.strip().lower()
            if clean and len(clean) >= 3 and clean not in seen:
                seen.add(clean)
                merged.append(clean)
        return merged
