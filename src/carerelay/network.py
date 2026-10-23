"""Access to the mock plans and provider network in data/network.py.

data/network.py (and its JSON) is the single source of truth for plans, providers, slots and prices; the
Insurance and Next Steps agents call it through here instead of copying it. It is loaded by path under a
private module name, so it does not collide with data/tests importing it as plain ``network``.
"""

from __future__ import annotations

import importlib.util
import sys
from functools import cache
from types import ModuleType


@cache
def net() -> ModuleType:
    from carerelay.service import find_data_dir  # lazy: service imports the agents that import this module

    path = find_data_dir() / "network.py"
    spec = importlib.util.spec_from_file_location("carerelay_data_network", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
