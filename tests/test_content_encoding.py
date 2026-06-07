"""
Encoding guard for user-facing content JSON.

Catches "mojibake" — text whose UTF-8 bytes were decoded as Windows-1252 and
re-saved, so a single character like an em-dash (—) becomes the garble "â€"".
This shipped once in data/fun_content.json (143 corrupted em-dashes the heartbeat
posted to Discord every 8h, seen as a "weird placeholder ae"); this test fails
the build if it reappears in any content file edited on a Windows box.

    python tests/test_content_encoding.py    # plain-asserts (runs in CI)
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# User-facing content the bot posts verbatim. Not the generated *.db or numeric
# weights files (those carry incidental, harmless non-ASCII in description fields).
def _content_files():
    data = os.path.join(_ROOT, "data")
    files = [
        os.path.join(data, "fun_content.json"),
        os.path.join(data, "boss_strats.json"),
    ]
    files += glob.glob(os.path.join(data, "strategy", "*.json"))
    files += glob.glob(os.path.join(data, "diagrams", "*.json"))
    return [f for f in files if os.path.exists(f)]


# Telltale CP1252 double-encode sequences: a stray 'â'/'Ã'/'Â' immediately
# followed by another non-ASCII byte is mojibake, never legitimate prose.
def _mojibake_runs(s):
    runs, i, n = [], 0, len(s)
    while i < n:
        if s[i] in ("â", "Ã", "Â") and i + 1 < n and ord(s[i + 1]) > 127:
            j = i
            while j < n and ord(s[j]) > 127:
                j += 1
            runs.append(s[i:j])
            i = j
        else:
            i += 1
    return runs


def _walk_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _walk_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_strings(v)


def test_no_mojibake_in_content():
    offenders = []
    for f in _content_files():
        # utf-8-sig: content files carry a BOM (PowerShell ConvertTo-Json).
        with open(f, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        for s in _walk_strings(data):
            for run in _mojibake_runs(s):
                offenders.append((os.path.relpath(f, _ROOT), run, s[:80]))
    assert not offenders, "mojibake (double-encoded UTF-8) found in content:\n" + "\n".join(
        f"  {path}: {run!r} in {ctx!r}" for path, run, ctx in offenders[:20]
    )


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} content-encoding tests passed")


if __name__ == "__main__":
    _main()
