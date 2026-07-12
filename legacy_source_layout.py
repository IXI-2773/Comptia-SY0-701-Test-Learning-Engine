from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LEGACY_PROJECT_ROOT = BASE_DIR.parent

if not (BASE_DIR / "smart_practice_concept_graph.py").exists() and str(LEGACY_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(LEGACY_PROJECT_ROOT))
