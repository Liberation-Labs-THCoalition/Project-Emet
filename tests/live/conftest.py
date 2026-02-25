"""Configuration for live integration tests.

These tests require real API access and should only run on the research
cluster with API keys configured.  They are skipped by default in CI
unless explicitly invoked with ``pytest -m live tests/live/``.

Required env vars (set in .env or cluster secrets):
    ALEPH_HOST               - Aleph instance URL (OpenAleph or Pro)
    ALEPH_API_KEY            - Aleph API key
    OPENSANCTIONS_API_KEY    - OpenSanctions screening API
    OPENCORPORATES_API_TOKEN - OpenCorporates corporate search
    COMPANIES_HOUSE_API_KEY  - UK Companies House (free)
    ETHERSCAN_API_KEY        - Etherscan blockchain explorer (free)
    ANTHROPIC_API_KEY        - Anthropic Claude (for LLM decision tests)

Optional:
    EDGAR_USER_AGENT         - SEC EDGAR (free, no key, just User-Agent)
    OLLAMA_HOST              - Ollama local LLM server URL
"""

from __future__ import annotations

import os
import tempfile

import pytest
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires real API access")
    config.addinivalue_line("markers", "live_slow: live test taking >30 seconds")
    config.addinivalue_line("markers", "live_llm: requires Anthropic or Ollama")
    config.addinivalue_line("markers", "live_blockchain: requires Etherscan API key")
    config.addinivalue_line("markers", "live_aleph: requires Aleph instance")


# ---------------------------------------------------------------------------
# API key availability checks
# ---------------------------------------------------------------------------

@dataclass
class LiveTestConfig:
    """Tracks which APIs are available for testing."""
    aleph_host: str = ""
    aleph_key: str = ""
    opensanctions_key: str = ""
    opencorporates_key: str = ""
    companies_house_key: str = ""
    etherscan_key: str = ""
    anthropic_key: str = ""
    ollama_host: str = ""
    edgar_user_agent: str = ""

    @classmethod
    def from_env(cls) -> "LiveTestConfig":
        return cls(
            aleph_host=os.getenv("ALEPH_HOST", ""),
            aleph_key=os.getenv("ALEPH_API_KEY", ""),
            opensanctions_key=os.getenv("OPENSANCTIONS_API_KEY", ""),
            opencorporates_key=os.getenv("OPENCORPORATES_API_TOKEN", ""),
            companies_house_key=os.getenv("COMPANIES_HOUSE_API_KEY", ""),
            etherscan_key=os.getenv("ETHERSCAN_API_KEY", ""),
            anthropic_key=os.getenv("ANTHROPIC_API_KEY", ""),
            ollama_host=os.getenv("OLLAMA_HOST", ""),
            edgar_user_agent=os.getenv("EDGAR_USER_AGENT", ""),
        )

    @property
    def has_aleph(self) -> bool:
        return bool(self.aleph_host and self.aleph_key)

    @property
    def has_opensanctions(self) -> bool:
        return bool(self.opensanctions_key)

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
        return bool(self.anthropic_key or self.ollama_host)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_key)

    @property
    def available_sources(self) -> list[str]:
        sources = ["icij", "gleif", "edgar"]  # Always available (no key)
        if self.has_aleph:
            sources.append("aleph")
        if self.has_opensanctions:
            sources.append("opensanctions")
        if self.has_opencorporates:
            sources.append("opencorporates")
        if self.has_companies_house:
            sources.append("companies_house")
        return sources


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def live_config() -> LiveTestConfig:
    """Session-scoped config — loaded once per test run."""
    return LiveTestConfig.from_env()


@pytest.fixture
def tmp_dir():
    """Temporary directory for session/audit output."""
    d = tempfile.mkdtemp(prefix="emet_live_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def require_aleph(live_config):
    if not live_config.has_aleph:
        pytest.skip("ALEPH_HOST and ALEPH_API_KEY not set")


@pytest.fixture
def require_opensanctions(live_config):
    if not live_config.has_opensanctions:
        pytest.skip("OPENSANCTIONS_API_KEY not set")


@pytest.fixture
def require_opencorporates(live_config):
    if not live_config.has_opencorporates:
        pytest.skip("OPENCORPORATES_API_TOKEN not set")


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
        pytest.skip("No LLM available (ANTHROPIC_API_KEY or OLLAMA_HOST)")


@pytest.fixture
def require_anthropic(live_config):
    if not live_config.has_anthropic:
        pytest.skip("ANTHROPIC_API_KEY not set")


@pytest.fixture
def require_any_source(live_config):
    if not live_config.available_sources:
        pytest.skip("No API keys configured for any data source")
