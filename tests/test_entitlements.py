"""
Entitlement gate tests — `core.entitlements.llm_enabled` is what turns the LLM
features on/off per guild. Pure logic with the DB calls stubbed.

    python tests/test_entitlements.py    # plain-asserts (runs in CI)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core import entitlements as E


def test_llm_enabled_gate():
    orig_enable = config.ENABLE_LLM
    orig_pro, orig_count = E.is_pro, E.count_command_month
    try:
        E.is_pro = lambda gid, *a, **k: gid == "proguild"
        E.count_command_month = lambda gid, cmd, *a, **k: 0

        config.ENABLE_LLM = False
        assert E.llm_enabled("proguild") is False        # backend off → always off

        config.ENABLE_LLM = True
        assert E.llm_enabled("global") is True           # unknown guild → pre-Pro behavior
        assert E.llm_enabled("") is True
        assert E.llm_enabled("freeguild") is False       # not Pro → off
        assert E.llm_enabled("proguild") is True         # Pro + under cap → on

        E.count_command_month = lambda gid, cmd, *a, **k: E.PRO_LLM_MONTHLY_CAP
        assert E.llm_enabled("proguild") is False        # over monthly cap → off
    finally:
        config.ENABLE_LLM = orig_enable
        E.is_pro, E.count_command_month = orig_pro, orig_count


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} entitlement tests passed")


if __name__ == "__main__":
    _main()
