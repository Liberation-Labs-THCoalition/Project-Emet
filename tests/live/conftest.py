"""Configuration for live integration tests.

These tests require real API access and should only run on the research
cluster with API keys configured.  They are skipped by default in CI
unless explicitly invoked with `pytest -m live`.

Environment variables (set in .env or cluster secrets):
    OPENSANCTIONS_API_URL   - yente API endpoint
    OPENCORPORATES_API_KEY  - OpenCorporates API token
    COMPANIES_HOUSE_API_KEY - UK Companies House API key
    ETHERSCAN_API_KEY       - Etherscan.io API key
    TRON_API_KEY            - TronGrid API key (optional)
    ANTHROPIC_API_KEY       - Anthropic API key (for LLM fallback tests)
    OLLAMA_BASE_URL         - Ollama server URL (default http://localhost:11434)
"""

from __future__ import annotations

import os
import pytest
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires real API access")
    config.addinivalue_line("markers", "live_slow: live test taking >30 seconds")
    config.addinivalue_line("markers", "live_llm: requires Ollama or Anthropic")
    config.addinivalue_line("markers", "live_blockchain: requires blockchain API keys")


# ---------------------------------------------------------------------------
# API key availability checks
# ---------------------------------------------------------------------------

@dataclass
class LiveTestConfig:
    """Tracks which APIs are available for testing."""
    opensanctions_url: str = ""
    opencorporates_key: str = ""
    companies_house_key: str = ""
    etherscan_key: str = ""
    tron_key: str = ""
    anthropic_key: str = ""
    ollama_url: str = ""

    @classmethod
    def from_env(cls) -> "LiveTestConfig":
        return cls(
            opensanctions_url=os.getenv("OPENSANCTIONS_API_URL", ""),
            opencorporates_key=os.getenv("OPENCORPORATES_API_KEY", ""),
            companies_house_key=os.getenv("COMPANIES_HOUSE_API_KEY", ""),
            etherscan_key=os.getenv("ETHERSCAN_API_KEY", ""),
            tron_key=os.getenv("TRON_API_KEY", ""),
            anthropic_key=os.getenv("ANTHROPIC_API_KEY", ""),
            ollama_url=os.getenv("OLLAMA_BASE_URL", ""),
        )

    @property
    def has_opensanctions(self) -> bool:
        return bool(self.opensanctions_url)

    @property
    def has_opencorporates(self) -> bool:
        return bool(self.opencorporates_key)

    @property
    def has_companies_house(self) -> bool:
        return bool(self.companies_house_key)

    @property
    def has_blockchain(self) -> bool:
        return bool(self.etherscan_key)

    @property
    def has_llm(self) -> bool:
        return bool(self.anthropic_key or self.ollama_url)

    @property
    def available_sources(self) -> list[str]:
        sources = []
        if self.has_opensanctions:
            sources.append("opensanctions")
        if self.has_opencorporates:
            sources.append("opencorporates")
        if self.has_companies_house:
            sources.append("companies_house")
        if self.has_blockchain:
            sources.append("blockchain")
        return sources


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def live_config() -> LiveTestConfig:
    """Session-scoped config — loaded once per test run."""
    return LiveTestConfig.from_env()


@pytest.fixture
def require_opensanctions(live_config):
    if not live_config.has_opensanctions:
        pytest.skip("OPENSANCTIONS_API_URL not set")


@pytest.fixture
def require_opencorporates(live_config):
    if not live_config.has_opencorporates:
        pytest.skip("OPENCORPORATES_API_KEY not set")


@pytest.fixture
def require_companies_house(live_config):
    if not live_config.has_companies_house:
        pytest.skip("COMPANIES_HOUSE_API_KEY not set")


@pytest.fixture
def require_blockchain(live_config):
    if not live_config.has_blockchain:
        pytest.skip("ETHERSCAN_API_KEY not set")


@pytest.fixture
def require_llm(live_config):
    if not live_config.has_llm:
        pytest.skip("No LLM available (ANTHROPIC_API_KEY or OLLAMA_BASE_URL)")


@pytest.fixture
def require_any_source(live_config):
    if not live_config.available_sources:
        pytest.skip("No API keys configured for any data source")
