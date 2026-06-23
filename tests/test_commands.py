"""Test that all 8 commands return non-empty, appropriate text with a freshness note."""
import pytest
from unittest.mock import patch

from app.schemas import FindingSchema
from app.cleaning import _make_hash
from app.analysis import build_report, COMMAND_INSTRUCTIONS

VALID_COMMANDS = ["scout", "alerts", "competitors", "campaigns", "opportunities", "pricing", "content", "help"]


def _sample_findings():
    items = [
        ("Baskin Robbins Pakistan", "instagram", "new_product",
         "New Strawberry Cheesecake ice cream now available! Summer launch 2026. Try it today."),
        ("Layers", "instagram", "discount",
         "50% off all cakes this Eid weekend! Special bakery dessert deal offer for all flavors."),
        ("Tehzeeb Bakers", "website", "menu_change",
         "New brownie and cheesecake menu now at all Islamabad branches. Prices from PKR 350."),
        ("Burning Brownie", "google_maps", "review_trend",
         "Burning Brownie has a Google Maps rating of 4.6/5 (312 reviews). Location: F-6, Islamabad."),
        ("Kitchen Cuisine", "google_maps", "review_trend",
         "[2 months ago] Amazing Ferrero Rocher cake at Kitchen Cuisine! Best dessert bakery in F-10."),
    ]
    findings = []
    for name, platform, update, text in items:
        findings.append(FindingSchema(
            competitor_name=name,
            source_platform=platform,
            update_type=update,
            content_text=text,
            content_hash=_make_hash(name, text),
            ai_summary=f"{name} is making a notable move with {update}.",
            relevance_score=8,
        ))
    return findings


@pytest.mark.parametrize("command", VALID_COMMANDS)
def test_command_returns_non_empty(command, monkeypatch):
    """Each command must return a non-empty string."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    findings = _sample_findings()
    freshness = "Data: live this run"

    with patch("app.analysis._chat", return_value=(
        f"1. Baskin Robbins launched new ice cream flavor.\n"
        f"2. Layers is running a 50% Eid discount.\n"
        f"3. Sugar Rush should counter with a brownie-sundae bundle."
    )):
        result = build_report(command, findings, freshness)

    assert isinstance(result, str)
    assert len(result) > 10


@pytest.mark.parametrize("command", [c for c in VALID_COMMANDS if c != "help"])
def test_command_includes_freshness_note(command, monkeypatch):
    """Every non-help command response must include a freshness note."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    findings = _sample_findings()
    freshness = "Data: live this run"

    with patch("app.analysis._chat", return_value="Baskin Robbins launched new flavor. Sugar Rush should respond."):
        result = build_report(command, findings, freshness)

    assert "Data:" in result


def test_help_command_lists_all_commands(monkeypatch):
    """help command must list all 8 commands."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    result = build_report("help", [], "")
    for cmd in ["scout", "alerts", "competitors", "campaigns", "opportunities", "pricing", "content", "help"]:
        assert cmd in result.lower()


def test_unknown_command_falls_back_to_scout_instruction(monkeypatch):
    """Unknown command falls back gracefully."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    findings = _sample_findings()
    with patch("app.analysis._chat", return_value="Baskin Robbins leads. Sugar Rush should counter."):
        result = build_report("unknown_xyz", findings, "Data: live this run")
    assert isinstance(result, str)
    assert len(result) > 0


def test_no_groq_key_returns_graceful_message(monkeypatch):
    """If GROQ_API_KEY is absent, return honest error rather than crashing."""
    monkeypatch.setenv("GROQ_API_KEY", "")
    import app.config as cfg
    original = cfg.GROQ_API_KEY
    cfg.GROQ_API_KEY = ""
    try:
        from app import analysis
        analysis_mod_key = analysis.GROQ_API_KEY if hasattr(analysis, "GROQ_API_KEY") else ""
        result = build_report("scout", _sample_findings(), "Data: live this run")
        assert isinstance(result, str)
        assert "unavailable" in result.lower() or "groq" in result.lower() or "key" in result.lower()
    finally:
        cfg.GROQ_API_KEY = original


def test_empty_findings_returns_honest_no_data_message(monkeypatch):
    """Empty findings → honest message."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    import app.config as cfg
    cfg.GROQ_API_KEY = "test-key"
    result = build_report("scout", [], "Data: live this run")
    assert isinstance(result, str)
    assert len(result) > 10
