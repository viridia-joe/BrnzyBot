"""
Canonical fight-diagram serving — runtime path needs no Pillow (reads a committed
PNG). Verifies the lookup contract that /bossguide relies on.

    python tests/test_fight_diagrams.py     # plain-asserts (runs in CI)
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import fight_diagrams as FD


def test_get_canonical_contract():
    # Unknown boss → None (so /bossguide falls back to procedural/text).
    assert FD.get_canonical("definitely_not_a_boss") is None

    orig = FD.DIAGRAM_DIR
    tmp = tempfile.mkdtemp()
    try:
        FD.DIAGRAM_DIR = tmp
        assert FD.has_canonical("gruul") is False
        assert FD.get_canonical("gruul") is None

        png = b"\x89PNG\r\n\x1a\n--canonical--"
        with open(os.path.join(tmp, "gruul.png"), "wb") as f:
            f.write(png)

        assert FD.has_canonical("gruul") is True
        assert FD.get_canonical("gruul") == png
    finally:
        FD.DIAGRAM_DIR = orig


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} fight-diagram tests passed")


if __name__ == "__main__":
    _main()
