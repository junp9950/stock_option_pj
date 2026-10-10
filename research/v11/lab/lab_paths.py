"""Local source paths and explicitly configured external data/application paths."""
import os
import sys
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("STOCK_LAB_DATA", LAB_DIR.parent / "data")).resolve()
APP_ROOT = Path(os.environ.get("STOCK_APP_ROOT", LAB_DIR.parent)).resolve()
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(LAB_DIR))
