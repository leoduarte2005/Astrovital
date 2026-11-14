"""CLI entry point for the Edge AI read-only SQLite repository."""
import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "edge-ai/src/edgespace_ai/clinical.py"
_SPEC = importlib.util.spec_from_file_location("edgespace_clinical_sqlite", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
ClinicalRepository = _MODULE.ClinicalRepository
