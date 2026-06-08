"""
JSON validity guard for all data files the bot loads at runtime.
Catches broken JSON before it reaches the VM and crashes commands.

    python tests/test_json_validity.py    # plain-asserts (runs in CI)
"""

import glob
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# All JSON files the bot loads directly.  Add paths here when new data files appear.
def _data_files():
    data = os.path.join(_ROOT, "data")
    files = []
    for pattern in (
        os.path.join(data, "rotations", "*.json"),
        os.path.join(data, "strategy", "*.json"),
        os.path.join(data, "diagrams", "*.json"),
        os.path.join(data, "set_bonuses.json"),
        os.path.join(data, "gem_db.json"),
        os.path.join(data, "meta_gems.json"),
        os.path.join(data, "fun_content.json"),
        os.path.join(data, "healer_thresholds.json"),
    ):
        files.extend(glob.glob(pattern))
    return sorted(f for f in files if os.path.exists(f))


def test_all_data_json_valid():
    errors = []
    for path in _data_files():
        try:
            with open(path, encoding="utf-8-sig") as f:
                json.load(f)
        except Exception as e:
            errors.append(f"{os.path.relpath(path, _ROOT)}: {e}")
    assert not errors, "Invalid JSON in data files:\n" + "\n".join(errors)


def test_rotation_profiles_no_unicode_punctuation():
    """Fancy Unicode (em-dashes, curly quotes) breaks Discord on some clients."""
    FORBIDDEN = ["—", "–", "‘", "’", "“", "”", "…"]
    errors = []
    for path in glob.glob(os.path.join(_ROOT, "data", "rotations", "*.json")):
        text = open(path, encoding="utf-8-sig").read()
        for ch in FORBIDDEN:
            if ch in text:
                name = os.path.basename(path)
                errors.append(f"{name} contains {repr(ch)} (U+{ord(ch):04X})")
    assert not errors, "Unicode fancy punctuation in rotation profiles:\n" + "\n".join(errors)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok  {t.__name__}")
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    sys.exit(failed)
