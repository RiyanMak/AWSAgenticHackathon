import os
import sys
from pathlib import Path

# Make the carerelay package importable without an install, and keep tests offline.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("CARERELAY_USE_AWS", None)
