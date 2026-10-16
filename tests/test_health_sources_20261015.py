"""`emet status` says which sources an investigation queries, read from the federation's own configuration, so it
can't drift from what runs (Vera's audit, 2026-10-14)."""
import pytest

from emet.agent.health import HealthCheck, _check_sources

KEYS = ["ALEPH_HOST", "ALEPH_API_KEY", "OPENSANCTIONS_API_KEY", "OPENCORPORATES_API_TOKEN", "COMPANIES_HOUSE_API_KEY",
        "EDGAR_USER_AGENT", "FEC_API_KEY", "COURTLISTENER_API_TOKEN", "EMET_CONGRESS_DATA_DIR"]


@pytest.fixture
def bare(monkeypatch, tmp_path):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)                    # no ./congress_data here
    return monkeypatch


def _by_name():
    return {c.name: c for c in _check_sources()}


def test_with_no_keys_the_keyed_sources_are_off_and_say_which_key(bare):
    s = _by_name()
    for name, key in [("Aleph", "ALEPH_API_KEY"), ("OpenSanctions", "OPENSANCTIONS_API_KEY"),
                      ("OpenCorporates", "OPENCORPORATES_API_TOKEN"), ("UK Companies House", "COMPANIES_HOUSE_API_KEY")]:
        assert s[name].status == "warning" and s[name].message.startswith("Off") and key in s[name].suggestion


def test_with_no_keys_the_free_sources_are_live_or_reduced(bare):
    s = _by_name()
    assert s["ICIJ Offshore Leaks"].status == "ok" and s["GLEIF"].status == "ok"
    assert s["FEC"].status == "info" and "DEMO_KEY" in s["FEC"].message
    assert s["CourtListener"].status == "info" and "unauthenticated" in s["CourtListener"].message
    assert s["SEC EDGAR"].status == "info" and "EDGAR_USER_AGENT" in s["SEC EDGAR"].message


def test_congress_without_local_data_says_it_returns_nothing(bare):
    c = _by_name()["Congress trades"]
    assert c.status == "warning" and "Returns nothing" in c.message


def test_congress_with_local_data_is_live(bare, tmp_path):
    d = tmp_path / "cd"
    d.mkdir()
    (d / "transactions.json").write_text("[]")
    bare.setenv("EMET_CONGRESS_DATA_DIR", str(d))
    assert _by_name()["Congress trades"].status == "ok"


def test_keys_turn_sources_on(bare):
    bare.setenv("OPENSANCTIONS_API_KEY", "x")
    bare.setenv("FEC_API_KEY", "x")
    bare.setenv("ALEPH_HOST", "https://aleph.example")
    s = _by_name()
    assert s["OpenSanctions"].status == "ok" and s["FEC"].status == "ok"
    assert s["Aleph"].status == "warning"          # the host alone isn't enough
    bare.setenv("ALEPH_API_KEY", "x")
    assert _by_name()["Aleph"].status == "ok"


def test_the_report_includes_the_sources(bare):
    names = {c.name for c in HealthCheck.run().checks}
    assert {"Aleph", "FEC", "Congress trades"} <= names
