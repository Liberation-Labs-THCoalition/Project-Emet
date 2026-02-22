"""Tests for adapter-to-investigation bridge wiring.

Verifies that Slack and Discord adapters properly delegate /investigate
and !investigate commands to the InvestigationBridge.
"""

from __future__ import annotations

import pytest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from emet.adapters.investigation_bridge import InvestigationBridge, BridgeConfig, InvestigationResult
from emet.agent.session import Session, Finding


# ---------------------------------------------------------------------------
# Slack handler wiring
# ---------------------------------------------------------------------------


class TestSlackInvestigateCommand:
    """Verify /kintsugi investigate command routes through the bridge."""

    def _make_handler(self, bridge=None):
        """Create a SlackEventHandler with mocked adapter/pairing."""
        from emet.adapters.slack.handlers import SlackEventHandler

        adapter = MagicMock()
        adapter.config.default_org_id = "test-org"
        adapter.config.require_pairing = False
        adapter.config.is_channel_type_allowed.return_value = True

        pairing = MagicMock()

        handler = SlackEventHandler(adapter, pairing)
        if bridge:
            handler.set_investigation_bridge(bridge)
        return handler

    @pytest.mark.asyncio
    async def test_investigate_command_routes_to_bridge(self):
        """Slash command should delegate to bridge."""
        bridge = InvestigationBridge(BridgeConfig(max_turns=2))

        handler = self._make_handler(bridge=bridge)

        ack = AsyncMock()
        respond = AsyncMock()

        command = {
            "user_id": "U123",
            "channel_id": "C456",
            "text": "investigate Acme Corp Panama",
        }

        await handler.handle_slash_command(command, ack, respond)

        # ack() should be called first
        ack.assert_awaited_once()

        # respond should have been called multiple times
        # (initial ack + bridge progress + final result)
        assert respond.await_count >= 2

    @pytest.mark.asyncio
    async def test_investigate_no_goal_shows_error(self):
        """Empty investigate goal should show usage help."""
        bridge = InvestigationBridge()
        handler = self._make_handler(bridge=bridge)

        ack = AsyncMock()
        respond = AsyncMock()

        command = {
            "user_id": "U123",
            "channel_id": "C456",
            "text": "investigate",
        }

        await handler.handle_slash_command(command, ack, respond)

        ack.assert_awaited_once()
        # Should show error about missing goal
        respond.assert_awaited()
        call_kwargs = respond.call_args_list[-1]
        assert "blocks" in call_kwargs.kwargs or "blocks" in (call_kwargs.args[0] if call_kwargs.args else {})

    @pytest.mark.asyncio
    async def test_investigate_no_bridge_shows_error(self):
        """No bridge configured should show admin error."""
        handler = self._make_handler(bridge=None)  # no bridge

        ack = AsyncMock()
        respond = AsyncMock()

        command = {
            "user_id": "U123",
            "channel_id": "C456",
            "text": "investigate Acme Corp",
        }

        await handler.handle_slash_command(command, ack, respond)

        ack.assert_awaited_once()
        respond.assert_awaited()

    @pytest.mark.asyncio
    async def test_investigation_bridge_setter(self):
        """set_investigation_bridge should store the bridge."""
        handler = self._make_handler()
        assert handler._investigation_bridge is None

        bridge = InvestigationBridge()
        handler.set_investigation_bridge(bridge)
        assert handler._investigation_bridge is bridge


# ---------------------------------------------------------------------------
# Discord adapter wiring
# ---------------------------------------------------------------------------


class TestDiscordInvestigateCommand:
    """Verify !investigate command routes through the bridge."""

    def _make_adapter(self, bridge=None, client=None):
        """Create a DiscordAdapter with mocked dependencies."""
        from emet.adapters.discord.bot import DiscordAdapter
        from emet.adapters.discord.config import DiscordConfig
        from emet.adapters.shared import PairingManager, PairingConfig

        config = DiscordConfig(
            bot_token="test-token",
            application_id="test-app-id",
            command_prefix="!",
        )
        pairing = PairingManager(PairingConfig())

        adapter = DiscordAdapter(config=config, pairing=pairing, client=client)
        if bridge:
            adapter.set_investigation_bridge(bridge)
        return adapter

    def test_parse_investigate_command(self):
        """!investigate should be parsed as a command."""
        adapter = self._make_adapter()
        cmd, args = adapter.parse_command("!investigate Acme Corp")
        assert cmd == "investigate"
        assert args == ["Acme", "Corp"]

    @pytest.mark.asyncio
    async def test_investigate_command_returns_embed(self):
        """!investigate should return a Discord embed."""
        bridge = InvestigationBridge(BridgeConfig(max_turns=2))
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value={"id": "msg-001"})

        adapter = self._make_adapter(bridge=bridge, client=mock_client)

        embed = await adapter.handle_investigate_command(
            channel_id="discord-ch-001",
            goal="Acme Corp Panama",
        )

        assert embed is not None
        assert "title" in embed
        assert "fields" in embed

    @pytest.mark.asyncio
    async def test_investigate_no_bridge_returns_none(self):
        """No bridge configured should return None."""
        adapter = self._make_adapter(bridge=None)

        result = await adapter.handle_investigate_command(
            channel_id="ch-001",
            goal="Test goal",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_investigate_empty_goal_returns_error(self):
        """Empty goal should return error embed."""
        bridge = InvestigationBridge()
        adapter = self._make_adapter(bridge=bridge)

        result = await adapter.handle_investigate_command(
            channel_id="ch-001",
            goal="",
        )
        assert result is not None
        assert result["color"] == 0xFF0000
        assert "Missing" in result["title"]

    def test_investigation_bridge_setter(self):
        """set_investigation_bridge should store the bridge."""
        adapter = self._make_adapter()
        assert adapter._investigation_bridge is None

        bridge = InvestigationBridge()
        adapter.set_investigation_bridge(bridge)
        assert adapter._investigation_bridge is bridge


# ---------------------------------------------------------------------------
# Bridge → Adapter formatting round-trip
# ---------------------------------------------------------------------------


class TestBridgeFormattingRoundTrip:
    """Test that bridge formatting produces valid adapter payloads."""

    def _make_result(self, goal="Test", error=""):
        """Helper to create an InvestigationResult."""
        session = Session(goal=goal)
        session.add_finding(Finding(
            source="search_entities",
            summary="Found 5 entities linked to offshore companies",
            confidence=0.85,
        ))
        return InvestigationResult(
            session=session,
            summary={
                "turns": 3,
                "entity_count": 5,
                "finding_count": 1,
                "leads_open": 2,
                "leads_total": 4,
                "unique_tools": ["search_entities", "trace_ownership"],
            },
            report_text="**Investigation Report**\nFindings here...",
            scrubbed_report_text="**Investigation Report**\nFindings here...",
            error=error,
        )

    def test_slack_blocks_structure(self):
        """Slack blocks should have header + summary at minimum."""
        bridge = InvestigationBridge()
        result = self._make_result("Acme Corp")

        msg = bridge.format_for_slack(result)
        assert isinstance(msg["blocks"], list)
        assert len(msg["blocks"]) >= 2

        # First block should be header
        assert msg["blocks"][0]["type"] == "header"

        # Should include findings block
        blocks_text = str(msg["blocks"])
        assert "offshore" in blocks_text.lower()

    def test_slack_error_blocks(self):
        """Slack error should produce a single section block."""
        bridge = InvestigationBridge()
        result = self._make_result(error="API timeout")

        msg = bridge.format_for_slack(result)
        assert "API timeout" in msg["text"]
        assert msg["blocks"][0]["type"] == "section"

    def test_discord_embed_fields(self):
        """Discord embed should have entity/finding/turn fields."""
        bridge = InvestigationBridge()
        result = self._make_result("Acme Corp")

        embed = bridge.format_for_discord(result)
        field_names = {f["name"] for f in embed["fields"]}
        assert "Entities" in field_names
        assert "Findings" in field_names
        assert "Turns" in field_names

    def test_discord_embed_has_findings(self):
        """Discord embed should include key findings in a field."""
        bridge = InvestigationBridge()
        result = self._make_result("Acme Corp")

        embed = bridge.format_for_discord(result)
        findings_field = next(
            (f for f in embed["fields"] if f["name"] == "Key Findings"),
            None,
        )
        assert findings_field is not None
        assert "offshore" in findings_field["value"].lower()

    def test_pii_scrub_note_in_slack(self):
        """If PII was scrubbed, Slack should show context element."""
        bridge = InvestigationBridge()
        result = self._make_result()
        result.pii_scrubbed = 3

        msg = bridge.format_for_slack(result)
        context_blocks = [b for b in msg["blocks"] if b["type"] == "context"]
        assert len(context_blocks) >= 1
        assert "3 PII" in str(context_blocks)

    def test_pii_scrub_note_in_discord(self):
        """If PII was scrubbed, Discord embed should have footer."""
        bridge = InvestigationBridge()
        result = self._make_result()
        result.pii_scrubbed = 7

        embed = bridge.format_for_discord(result)
        assert "footer" in embed
        assert "7 PII" in embed["footer"]["text"]
