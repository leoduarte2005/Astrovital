"""SQLite FTS5 (BM25, mode=ro, busy_timeout=5000) clinical store."""

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
    """Clinical guideline/protocol hit returned by SQLite FTS5."""

    doc_id: str
    title: str
    subsystem: str
    snippet: str
    score: float
    source: str  # "sqlite_fts5"
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
    """Queries SQLite FTS5 (BM25) in read-only mode across reports and protocols."""

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        knowledge_base_path: Optional[Path | str] = None,
    ) -> None:
        self._explicit_db_path = db_path is not None and Path(db_path) != DEFAULT_DB_PATH
        self.db_path = resolve_db_path(db_path)
        self.knowledge_base_path = Path(knowledge_base_path) if knowledge_base_path else None

    def search(self, query: str, *, concepts: Sequence[str] = (), limit: int = 5) -> list[ClinicalDocument]:
        """Search clinical reports and protocols via SQLite FTS5 BM25 (mode=ro)."""
        terms = self._build_search_terms(query, concepts)
        if not terms:
            return []
        return self._search_sqlite_fts5(terms, limit=limit)

    def _search_sqlite_fts5(self, terms: Sequence[str], *, limit: int) -> list[ClinicalDocument]:
        if not self.db_path.is_file() and not self._explicit_db_path:
            self.db_path = resolve_db_path(None)
        if not self.db_path.is_file():
            if self._explicit_db_path:
                raise FileNotFoundError(f"SQLite clinical database not found: {self.db_path}")
            return []

        uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            conn.execute("PRAGMA busy_timeout = 5000;")

            existing_fts = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND lower(sql) LIKE '%fts5%'"
                ).fetchall()
            }
            if not existing_fts:
                return []

            preferred_order = ["clinical_reports_fts", "protocols_fts"]
            ordered_tables = [t for t in preferred_order if t in existing_fts] + [
                t for t in sorted(existing_fts) if t not in preferred_order
            ]

            match_expr = " OR ".join(f'"{t}"' for t in terms[:12])
            per_table_limit = max(limit * 3, 10)
            fused_by_id: dict[str, ClinicalDocument] = {}

            for table_name in ordered_tables:
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
                    rows = conn.execute(sql, (match_expr, per_table_limit)).fetchall()
                except sqlite3.OperationalError:
                    continue

                table_raw: list[tuple[ClinicalDocument, float]] = []
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
                        or col_values.get("steps_json")
                        or title
                    )
                    source_id = str(col_values.get("source_id") or "")
                    if col_values.get("report_id"):
                        ref = conn.execute(
                            "SELECT source_id, payload_json, category FROM clinical_reports WHERE report_id=?",
                            (doc_id,),
                        ).fetchone()
                        if ref:
                            if ref[2] == "HAZARD":
                                continue
                            source_id = str(ref[0] or source_id)
                    raw_pos = max(1e-9, -bm25_score)
                    table_raw.append((
                        ClinicalDocument(
                            doc_id=doc_id,
                            title=title,
                            subsystem=subsystem,
                            snippet=snippet[:280],
                            score=raw_pos,
                            source="sqlite_fts5",
                            source_id=source_id,
                        ),
                        raw_pos,
                    ))

                if not table_raw:
                    continue
                max_pos = max(s for _, s in table_raw)
                min_pos = min(s for _, s in table_raw)
                span = max_pos - min_pos
                for doc, raw_pos in table_raw:
                    norm = 1.0 if span <= 1e-12 else 0.2 + 0.8 * ((raw_pos - min_pos) / span)
                    normalized_doc = ClinicalDocument(
                        doc_id=doc.doc_id,
                        title=doc.title,
                        subsystem=doc.subsystem,
                        snippet=doc.snippet,
                        score=norm,
                        source="sqlite_fts5",
                        source_id=doc.source_id,
                    )
                    prev = fused_by_id.get(doc.doc_id)
                    if prev is None or normalized_doc.score > prev.score:
                        fused_by_id[doc.doc_id] = normalized_doc

            results = list(fused_by_id.values())
            results.sort(key=lambda d: d.score, reverse=True)
            return results[:limit]
        except Exception as exc:
            raise RuntimeError("SQLite clinical search failed") from exc
        finally:
            if conn is not None:
                conn.close()

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
