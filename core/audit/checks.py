"""
Raid audit — result model.

Deterministic data structures for a per-raider log audit. A run produces an
``AuditReport`` made of three ``Section``s (Baseline / Execution / Preparation),
each holding a list of ``CheckResult``s. Every check carries a machine-readable
``evidence`` dict (the raw numbers) plus a human ``summary`` so the report can be
rendered with no LLM. An LLM, when enabled, can later narrate the same evidence.

This mirrors the maintainer's hand-written scorecard (see docs/RAID_AUDIT.md):
each line in that doc becomes a CheckResult with a Verdict.

No Discord I/O here, and no LLM — pure logic, returns strings/data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    """Outcome of a single check. Ordered roughly best → worst for sorting."""
    PASS = "pass"        # ✅ meets the ideal
    INFO = "info"        # ℹ️ context only, no judgement
    WARN = "warn"        # ⚠️ improvable / minor miss
    FAIL = "fail"        # ❌ clear miss vs the ideal
    UNKNOWN = "unknown"  # ❔ data unavailable from the log

    @property
    def icon(self) -> str:
        return {
            Verdict.PASS: "✅",
            Verdict.INFO: "ℹ️",
            Verdict.WARN: "⚠️",
            Verdict.FAIL: "❌",
            Verdict.UNKNOWN: "❔",
        }[self]


@dataclass
class CheckResult:
    """One line of the scorecard."""
    key: str                       # stable id, e.g. "enchants"
    label: str                     # display label, e.g. "Enchants"
    verdict: Verdict
    summary: str                   # one-line human summary
    detail: str = ""               # optional longer notes / advice
    evidence: dict = field(default_factory=dict)   # raw numbers for LLM/debug

    def render(self) -> str:
        line = f"{self.verdict.icon} **{self.label}:** {self.summary}"
        if self.detail:
            line += f"\n   _{self.detail}_"
        return line


@dataclass
class Section:
    """A group of checks: Baseline | Execution | Preparation."""
    name: str
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)

    def render(self) -> str:
        body = "\n".join(c.render() for c in self.checks) or "_no data_"
        return f"### {self.name}\n{body}"


@dataclass
class AuditReport:
    """Full audit for one character over a set of fights in one WCL report."""
    character: str
    spec: str
    report_code: str
    fight_ids: list[int] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # data-gathering caveats

    def render(self) -> str:
        """Deterministic Discord/markdown render, mirroring the scorecard doc."""
        head = f"# Raid Audit — {self.character} ({self.spec})"
        body = "\n\n".join(s.render() for s in self.sections)
        out = f"{head}\n\n{body}"
        if self.warnings:
            out += "\n\n" + "\n".join(f"> ⚠️ {w}" for w in self.warnings)
        return out
