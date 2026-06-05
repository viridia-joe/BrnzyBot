"""
Raid audit package — deterministic per-raider log analysis.

Takes a Warcraft Logs report and scores a character against a spec's "ideal
behaviors" rubric across three sections: Baseline, Execution, Preparation.
See docs/RAID_AUDIT.md for the design and core/audit/profiles.py for the rubric.

Public surface:
    build_audit(url, character, spec) -> AuditReport            # single raider
    build_roster_audit(url, resolve_spec) -> RosterAudit        # whole roster
    AuditReport.render() / RosterAudit.render() -> str
"""

from core.audit.checks import AuditReport, CheckResult, RosterAudit, Section, Verdict
from core.audit.normalize import normalize_combatant
from core.audit.profiles import SpecProfile, get_profile
from core.audit.report import (
    audit_combatant, build_audit, build_roster_audit, parse_report_url,
)

__all__ = [
    "AuditReport", "CheckResult", "RosterAudit", "Section", "Verdict",
    "SpecProfile", "get_profile", "normalize_combatant",
    "audit_combatant", "build_audit", "build_roster_audit", "parse_report_url",
]
