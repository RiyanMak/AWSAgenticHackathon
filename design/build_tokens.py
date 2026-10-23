"""Generate the theme files from design/tokens.json.

    python design/build_tokens.py          # writes both files
    python design/build_tokens.py --check  # exit 1 if either file is stale (used by tests)

Outputs:
  src/carerelay/ui/www/tokens.css  CSS custom properties for the Shiny UI (--color-course, ...)
  presentation/_tokens.scss    SCSS variables for the Quarto deck ($color-course, ...)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "design" / "tokens.json"
CSS = ROOT / "src" / "carerelay" / "ui" / "www" / "tokens.css"
SCSS = ROOT / "presentation" / "_tokens.scss"
HEADER = "Generated from design/tokens.json by design/build_tokens.py. Do not edit by hand."


def _flat(tokens: dict) -> list[tuple[str, str]]:
    return [(f"{group}-{name}", value) for group, items in tokens.items() if not group.startswith("_")
            for name, value in items.items() if not (group == "font" and name == "google")]


def render() -> dict[Path, str]:
    tokens = json.loads(TOKENS.read_text())
    flat = _flat(tokens)
    css = [f"/* {HEADER} */", f"@import url(\"{tokens['font']['google']}\");", ":root {"]
    css += [f"  --{k}: {v};" for k, v in flat] + ["}"]
    scss = [f"// {HEADER}", f"$font-google: \"{tokens['font']['google']}\";"]
    scss += [f"${k}: {v};" for k, v in flat]
    return {CSS: "\n".join(css) + "\n", SCSS: "\n".join(scss) + "\n"}


def main() -> int:
    stale = []
    for path, text in render().items():
        if "--check" in sys.argv:
            if not path.exists() or path.read_text() != text:
                stale.append(path.relative_to(ROOT))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print(f"stale: {', '.join(map(str, stale))}; run python design/build_tokens.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
