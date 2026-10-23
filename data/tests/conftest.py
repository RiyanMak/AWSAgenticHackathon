import sys
from pathlib import Path

# Make data/ modules (network, labs, build, render) importable without a package install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
