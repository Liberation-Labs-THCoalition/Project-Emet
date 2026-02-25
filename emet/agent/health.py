"""Emet health checks and maintenance scheduler.

Provides:
  1. System health check (API keys, data freshness, disk, dependencies)
  2. Crontab generator for automated maintenance
  3. Post-investigation hooks (next-step suggestions)

Usage:
    # CLI
    emet status                    # One-shot health check
    emet status --install-cron     # Set up automated checks

    # Programmatic
    from emet.agent.health import HealthCheck
    report = HealthCheck.run()
    print(report.summary)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Health check results
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Single health check result."""
    name: str
    status: str  # "ok", "warning", "error", "info"
    message: str
    suggestion: str = ""


@dataclass
class HealthReport:
    """Complete health report."""
    checks: list[CheckResult] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "ok")

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warning")

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "error")

    @property
    def summary(self) -> str:
        lines = [f"Emet Health Check — {self.timestamp[:19]}Z"]
        lines.append(f"  {self.ok_count} ok / {self.warning_count} warnings / {self.error_count} errors")
        lines.append("")

        for c in self.checks:
            icon = {"ok": "✅", "warning": "⚠️", "error": "❌", "info": "ℹ️"}.get(c.status, "?")
            lines.append(f"  {icon} {c.name}: {c.message}")
            if c.suggestion:
                lines.append(f"     → {c.suggestion}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_api_keys() -> list[CheckResult]:
    """Check which API keys are configured."""
    results = []

    keys = {
        "ALEPH_HOST + ALEPH_API_KEY": ("Aleph (core data platform)", ["ALEPH_HOST", "ALEPH_API_KEY"]),
        "OPENSANCTIONS_API_KEY": ("OpenSanctions (sanctions screening)", ["OPENSANCTIONS_API_KEY"]),
        "ANTHROPIC_API_KEY": ("Anthropic Claude (LLM decisions)", ["ANTHROPIC_API_KEY"]),
        "OPENCORPORATES_API_TOKEN": ("OpenCorporates (corporate registries)", ["OPENCORPORATES_API_TOKEN"]),
        "COMPANIES_HOUSE_API_KEY": ("UK Companies House (free)", ["COMPANIES_HOUSE_API_KEY"]),
        "ETHERSCAN_API_KEY": ("Etherscan (blockchain, free)", ["ETHERSCAN_API_KEY"]),
    }

    configured = 0
    for label, (desc, env_vars) in keys.items():
        all_set = all(os.environ.get(v) for v in env_vars)
        if all_set:
            configured += 1
            results.append(CheckResult(desc, "ok", "Configured"))
        else:
            results.append(CheckResult(
                desc, "warning", "Not configured",
                suggestion=f"Set {label} in .env"
            ))

    return results


def _check_data_freshness(memory_dir: str = "") -> list[CheckResult]:
    """Check when investigations were last run."""
    results = []

    # Check memory directory
    dirs_to_check = [memory_dir] if memory_dir else ["investigations", "emet_data"]
    found_dir = None

    for d in dirs_to_check:
        p = Path(d)
        if p.exists():
            found_dir = p
            break

    if not found_dir:
        results.append(CheckResult(
            "Investigation data", "info", "No investigation data found yet",
            suggestion="Run: emet investigate \"<your target>\""
        ))
        return results

    # Find most recent session
    sessions = sorted(found_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if sessions:
        latest = sessions[0]
        age_hours = (datetime.now(timezone.utc).timestamp() - latest.stat().st_mtime) / 3600
        age_days = age_hours / 24

        if age_days > 30:
            results.append(CheckResult(
                "Data freshness", "warning",
                f"Last investigation: {age_days:.0f} days ago ({latest.name})",
                suggestion="Sanctions lists and corporate records change daily. Consider re-running key investigations."
            ))
        elif age_days > 7:
            results.append(CheckResult(
                "Data freshness", "info",
                f"Last investigation: {age_days:.0f} days ago",
                suggestion="Sanctions data may have changed since last run."
            ))
        else:
            results.append(CheckResult(
                "Data freshness", "ok",
                f"Last investigation: {age_hours:.0f} hours ago"
            ))

    # Check audit archives
    audit_dir = found_dir / "audit"
    if audit_dir.exists():
        archives = list(audit_dir.glob("*.jsonl.gz"))
        results.append(CheckResult(
            "Audit archives", "ok" if archives else "info",
            f"{len(archives)} investigation archives stored"
        ))
    else:
        results.append(CheckResult(
            "Audit archives", "info", "No audit archives yet"
        ))

    return results


def _check_disk() -> list[CheckResult]:
    """Check available disk space."""
    results = []
    usage = shutil.disk_usage("/")
    free_gb = usage.free / (1024 ** 3)

    if free_gb < 1:
        results.append(CheckResult(
            "Disk space", "error", f"{free_gb:.1f} GB free",
            suggestion="Free up disk space — investigation archives and PDF reports need room."
        ))
    elif free_gb < 5:
        results.append(CheckResult(
            "Disk space", "warning", f"{free_gb:.1f} GB free",
            suggestion="Consider archiving old investigation data."
        ))
    else:
        results.append(CheckResult("Disk space", "ok", f"{free_gb:.1f} GB free"))

    return results


def _check_dependencies() -> list[CheckResult]:
    """Check that critical imports work."""
    results = []

    critical = {
        "httpx": "HTTP client (data source access)",
        "networkx": "Graph analytics engine",
        "reportlab": "PDF report generation",
    }

    for pkg, desc in critical.items():
        try:
            __import__(pkg)
            results.append(CheckResult(desc, "ok", f"{pkg} available"))
        except ImportError:
            results.append(CheckResult(
                desc, "error", f"{pkg} not installed",
                suggestion=f"pip install {pkg}"
            ))

    # Optional but valuable
    optional = {
        "anthropic": "LLM decisions (pip install anthropic)",
        "followthemoney": "FtM entity model (pip install emet[ftm])",
    }

    for pkg, desc in optional.items():
        try:
            __import__(pkg)
            results.append(CheckResult(desc, "ok", "Available"))
        except ImportError:
            results.append(CheckResult(desc, "info", "Not installed", suggestion=desc))

    return results


# ---------------------------------------------------------------------------
# Health check runner
# ---------------------------------------------------------------------------


class HealthCheck:
    """Run all health checks and produce a report."""

    @staticmethod
    def run(memory_dir: str = "") -> HealthReport:
        report = HealthReport()
        report.checks.extend(_check_api_keys())
        report.checks.extend(_check_data_freshness(memory_dir))
        report.checks.extend(_check_disk())
        report.checks.extend(_check_dependencies())
        return report


# ---------------------------------------------------------------------------
# Post-investigation hooks
# ---------------------------------------------------------------------------


@dataclass
class NextStep:
    """A suggested next action after an investigation."""
    action: str
    reason: str
    command: str  # CLI command to run it


def suggest_next_steps(session_summary: dict[str, Any]) -> list[NextStep]:
    """Analyze a completed investigation and suggest follow-ups.

    Called automatically at the end of every investigation.
    """
    steps: list[NextStep] = []
    goal = session_summary.get("goal", "")
    entity_count = session_summary.get("entity_count", 0)
    finding_count = session_summary.get("finding_count", 0)
    tools_used = set(session_summary.get("unique_tools", []))

    # Suggest sanctions screening if not done
    if "screen_sanctions" not in tools_used and entity_count > 0:
        steps.append(NextStep(
            action="Run sanctions screening",
            reason=f"{entity_count} entities found but not screened against sanctions lists",
            command=f'emet investigate "{goal} sanctions exposure"',
        ))

    # Suggest graph analysis if enough entities
    if "analyze_graph" not in tools_used and entity_count >= 5:
        steps.append(NextStep(
            action="Run network analysis",
            reason=f"{entity_count} entities could reveal hidden connections",
            command=f'emet investigate "{goal} network analysis"',
        ))

    # Suggest blockchain if financial indicators present
    if "investigate_blockchain" not in tools_used:
        financial_keywords = {"payment", "transfer", "wallet", "crypto", "bitcoin", "ethereum", "usdt"}
        if any(kw in goal.lower() for kw in financial_keywords):
            steps.append(NextStep(
                action="Investigate blockchain flows",
                reason="Financial keywords detected — blockchain may reveal payment trails",
                command=f'emet investigate "{goal} blockchain transactions"',
            ))

    # Suggest re-investigation schedule
    if finding_count > 0:
        steps.append(NextStep(
            action="Schedule re-check in 7 days",
            reason="Sanctions lists and corporate records update frequently",
            command=f'emet status --install-cron',
        ))

    return steps


# ---------------------------------------------------------------------------
# Crontab management
# ---------------------------------------------------------------------------


CRON_HEALTH_CHECK = "0 9 * * 1"  # Monday 9 AM
CRON_COMMENT = "# Emet automated health check"


def generate_crontab_entry() -> str:
    """Generate a crontab line for weekly health checks."""
    emet_path = shutil.which("emet") or "emet"
    return f"{CRON_HEALTH_CHECK} {emet_path} status --quiet >> /tmp/emet_health.log 2>&1  {CRON_COMMENT}"


def install_cron() -> tuple[bool, str]:
    """Install the Emet health check crontab entry.

    Returns (success, message).
    """
    try:
        # Read existing crontab
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=5,
        )
        existing = result.stdout if result.returncode == 0 else ""

        # Check if already installed
        if "emet" in existing and "status" in existing:
            return True, "Emet cron job already installed"

        # Append our entry
        new_crontab = existing.rstrip() + "\n\n" + generate_crontab_entry() + "\n"

        # Install
        proc = subprocess.run(
            ["crontab", "-"],
            input=new_crontab, capture_output=True, text=True, timeout=5,
        )

        if proc.returncode == 0:
            return True, f"Installed weekly health check (Mondays 9 AM): {generate_crontab_entry()}"
        else:
            return False, f"crontab install failed: {proc.stderr}"

    except FileNotFoundError:
        return False, "crontab not available on this system"
    except Exception as e:
        return False, f"Cron install failed: {e}"
