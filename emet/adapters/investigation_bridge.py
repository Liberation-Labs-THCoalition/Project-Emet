"""Investigation bridge — connects platform adapters to the agent.

When a user sends `/investigate "Acme Corp Panama"` in Slack, this
bridge translates that into an InvestigationAgent.investigate() call,
streams progress updates back to the adapter, and delivers the final
report.

Works with any adapter that implements BaseAdapter (Slack, Discord,
webchat, email). The bridge is adapter-agnostic — it speaks
AdapterMessage/AdapterResponse, not Slack blocks or Discord embeds.

Usage:
    bridge = InvestigationBridge()

    # From a Slack handler:
    response = await bridge.handle_investigate_command(
        message=adapter_message,
        adapter=slack_adapter,
    )

    # From the API:
    result = await bridge.run_investigation(goal="Acme Corp Panama")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

from emet.agent import InvestigationAgent, AgentConfig
from emet.agent.session import Session
from emet.agent.safety_harness import SafetyHarness

logger = logging.getLogger(__name__)


@dataclass
class InvestigationResult:
    """Result of a bridge-initiated investigation."""
    session: Session
    summary: dict[str, Any]
    report_text: str = ""
    scrubbed_report_text: str = ""
    pii_scrubbed: int = 0
    error: str = ""


@dataclass
class BridgeConfig:
    """Configuration for the investigation bridge."""
    max_turns: int = 15
    llm_provider: str = "stub"
    auto_sanctions: bool = True
    auto_news: bool = True
    enable_safety: bool = True
    generate_graph: bool = True
    # Progress callback — called after each turn
    # Signature: async callback(turn: int, action: str, summary: str) -> None
    progress_callback: Optional[
        Callable[[int, str, str], Coroutine[Any, Any, None]]
    ] = None


class InvestigationBridge:
    """Bridges platform adapters to the investigation engine.

    This is the single integration point. Adapters don't need to know
    about InvestigationAgent, Sessions, or safety harnesses — they
    just call handle_investigate_command() with a message and get back
    a formatted response.
    """

    def __init__(self, config: BridgeConfig | None = None) -> None:
        self._config = config or BridgeConfig()
        self._active: dict[str, Session] = {}  # channel_id → running session

    async def run_investigation(
        self,
        goal: str,
        config: BridgeConfig | None = None,
    ) -> InvestigationResult:
        """Run a full investigation and return results.

        This is the core method. Adapters and API endpoints both
        ultimately call this.
        """
        cfg = config or self._config

        agent_config = AgentConfig(
            max_turns=cfg.max_turns,
            llm_provider=cfg.llm_provider,
            auto_sanctions_screen=cfg.auto_sanctions,
            auto_news_check=cfg.auto_news,
            enable_safety=cfg.enable_safety,
            generate_graph=cfg.generate_graph,
        )

        agent = InvestigationAgent(config=agent_config)

        try:
            session = await agent.investigate(goal)
            summary = session.summary()

            # Build report text
            report_parts = [
                f"**Investigation: {goal}**",
                f"Turns: {summary['turns']} | "
                f"Entities: {summary['entity_count']} | "
                f"Findings: {summary['finding_count']}",
                "",
            ]

            if session.findings:
                report_parts.append("**Findings:**")
                for f in session.findings:
                    report_parts.append(f"• [{f.source}] {f.summary}")
                report_parts.append("")

            open_leads = session.get_open_leads()
            if open_leads:
                report_parts.append(f"**Open leads:** {len(open_leads)}")
                for lead in open_leads[:3]:
                    report_parts.append(f"• {lead.description}")
                report_parts.append("")

            report_text = "\n".join(report_parts)

            # Scrub for publication
            harness = SafetyHarness.from_defaults()
            pub = harness.scrub_for_publication(report_text, "adapter_report")

            return InvestigationResult(
                session=session,
                summary=summary,
                report_text=report_text,
                scrubbed_report_text=pub.scrubbed_text,
                pii_scrubbed=pub.pii_found,
            )

        except Exception as exc:
            logger.exception("Investigation failed: %s", goal)
            return InvestigationResult(
                session=Session(goal=goal),
                summary={},
                error=str(exc),
            )

    async def handle_investigate_command(
        self,
        goal: str,
        channel_id: str,
        send_fn: Callable[[str], Coroutine[Any, Any, None]],
    ) -> InvestigationResult:
        """Handle an /investigate command from any adapter.

        Args:
            goal: The investigation goal text
            channel_id: Where to send progress updates
            send_fn: Async function to send a message to the channel.
                      Signature: async send_fn(text: str) -> None

        Returns:
            InvestigationResult with session and formatted report
        """
        # Check for duplicate
        if channel_id in self._active:
            await send_fn(
                f"⚠️ Investigation already running in this channel: "
                f"'{self._active[channel_id].goal}'"
            )
            return InvestigationResult(
                session=Session(goal=goal),
                summary={},
                error="Investigation already running in this channel",
            )

        await send_fn(f"🔍 Starting investigation: {goal}")

        # Mark channel as active
        placeholder = Session(goal=goal)
        self._active[channel_id] = placeholder

        try:
            result = await self.run_investigation(goal)

            if result.error:
                await send_fn(f"❌ Investigation failed: {result.error}")
            else:
                # Send scrubbed report (publication boundary)
                await send_fn(result.scrubbed_report_text)

                if result.pii_scrubbed:
                    await send_fn(
                        f"ℹ️ {result.pii_scrubbed} PII items redacted from report"
                    )

            return result

        finally:
            # Always clean up
            self._active.pop(channel_id, None)

    def format_for_slack(self, result: InvestigationResult) -> dict[str, Any]:
        """Format investigation results as Slack blocks."""
        if result.error:
            return {
                "text": f"Investigation failed: {result.error}",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"❌ *Investigation failed*\n{result.error}",
                        },
                    }
                ],
            }

        summary = result.summary
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🔍 Investigation: {result.session.goal}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Entities:* {summary.get('entity_count', 0)}"},
                    {"type": "mrkdwn", "text": f"*Findings:* {summary.get('finding_count', 0)}"},
                    {"type": "mrkdwn", "text": f"*Turns:* {summary.get('turns', 0)}"},
                    {"type": "mrkdwn", "text": f"*Leads:* {summary.get('leads_open', 0)} open"},
                ],
            },
        ]

        # Findings
        if result.session.findings:
            findings_text = "\n".join(
                f"• [{f.source}] {f.summary[:100]}"
                for f in result.session.findings[:5]
            )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Findings:*\n{findings_text}"},
            })

        # Open leads
        open_leads = result.session.get_open_leads()
        if open_leads:
            leads_text = "\n".join(
                f"• {l.description[:80]}"
                for l in open_leads[:3]
            )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Open leads:*\n{leads_text}"},
            })

        if result.pii_scrubbed:
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"ℹ️ {result.pii_scrubbed} PII items redacted",
                    },
                ],
            })

        return {"text": result.scrubbed_report_text, "blocks": blocks}

    def format_for_discord(self, result: InvestigationResult) -> dict[str, Any]:
        """Format investigation results as a Discord embed."""
        if result.error:
            return {
                "title": "❌ Investigation Failed",
                "description": result.error,
                "color": 0xFF0000,
            }

        summary = result.summary
        fields = [
            {"name": "Entities", "value": str(summary.get("entity_count", 0)), "inline": True},
            {"name": "Findings", "value": str(summary.get("finding_count", 0)), "inline": True},
            {"name": "Turns", "value": str(summary.get("turns", 0)), "inline": True},
        ]

        if result.session.findings:
            findings_text = "\n".join(
                f"• [{f.source}] {f.summary[:80]}"
                for f in result.session.findings[:5]
            )
            fields.append({"name": "Key Findings", "value": findings_text, "inline": False})

        embed = {
            "title": f"🔍 {result.session.goal}",
            "description": f"Investigation complete — {summary.get('leads_open', 0)} leads remaining",
            "color": 0x2ECC71 if not result.error else 0xFF0000,
            "fields": fields,
        }

        if result.pii_scrubbed:
            embed["footer"] = {"text": f"{result.pii_scrubbed} PII items redacted"}

        return embed
