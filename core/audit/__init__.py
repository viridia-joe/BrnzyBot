"""
Raid audit package — deterministic per-raider log analysis.

Takes a Warcraft Logs report and scores a character against a spec's "ideal
behaviors" rubric across three sections: Baseline, Execution, Preparation.
See docs/RAID_AUDIT.md for the design and core/audit/profiles.py for the rubric.

Public surface:
    build_audit(url, character, spec) -> AuditReport
    AuditReport.render() -> str
"""

from core.audit.checks import AuditReport, CheckResult, Section, Verdict
from core.audit.profiles import SpecProfile, get_profile
from core.audit.report import build_audit, parse_report_url

__all__ = [
    "AuditReport", "CheckResult", "Section", "Verdict",
    "SpecProfile", "get_profile",
    "build_audit", "parse_report_url",
]
