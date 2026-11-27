"""Windows protokoll-kezelő: elmenti a com.lidlplus.app://callback URL-t.

A login parancs ideiglenesen regisztrálja ezt a szkriptet a
com.lidlplus.app:// sémára, így a böngésző callbackját automatikusan
el tudja kapni.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    target = Path(sys.argv[1])
    url = sys.argv[2]
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(url, encoding="utf-8")
    except OSError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
