"""
scripts/sanitize_json_text.py
Replace all fancy Unicode punctuation in JSON data files with plain ASCII equivalents.
Run before committing any JSON files that contain user-facing text.
"""
import glob
import json
import os
import sys

REPLACEMENTS = [
    ("—", " - "),   # em-dash
    ("–", " - "),   # en-dash
    ("‘", "'"),     # left single curly quote
    ("’", "'"),     # right single curly quote
    ("“", '"'),     # left double curly quote
    ("”", '"'),     # right double curly quote
    ("…", "..."),   # ellipsis
    ("â€“", " - "),  # mojibake em-dash variant 1
    ("â€”", " - "),  # mojibake em-dash variant 2
    ("â€™", "'"),    # mojibake apostrophe
    ("â€œ", '"'),    # mojibake left double quote
    ("â€", " - "),        # catch-all mojibake prefix
]


def sanitize(s: str) -> str:
    for bad, good in REPLACEMENTS:
        s = s.replace(bad, good)
    return s


def sanitize_obj(obj):
    if isinstance(obj, str):
        return sanitize(obj)
    if isinstance(obj, dict):
        return {k: sanitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_obj(v) for v in obj]
    return obj


def process(path: str) -> bool:
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    cleaned = sanitize_obj(data)
    out = json.dumps(cleaned, indent=2, ensure_ascii=False)
    json.loads(out)  # validate before writing
    with open(path, "w", encoding="utf-8") as f:
        f.write(out + "\n")
    return True


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    patterns = sys.argv[1:] or [
        os.path.join(root, "data", "rotations", "*.json"),
        os.path.join(root, "data", "fun_content.json"),
        os.path.join(root, "data", "boss_strats.json"),
        os.path.join(root, "data", "strategy", "*.json"),
    ]
    errors = 0
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            try:
                process(path)
                print(f"ok  {os.path.relpath(path, root)}")
            except Exception as e:
                print(f"ERR {os.path.relpath(path, root)}: {e}")
                errors += 1
    sys.exit(errors)
