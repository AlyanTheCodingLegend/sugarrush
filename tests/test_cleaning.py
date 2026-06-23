"""Unit tests for the cleaning layer. Fixtures are intentionally messy."""
import pytest
from datetime import datetime

from app.schemas import FindingSchema
from app.cleaning import clean_findings, clean_text, _is_noise, _make_hash


def _make(text, competitor="TestCo", platform="instagram", update="post", **kwargs):
    return FindingSchema(
        competitor_name=competitor,
        source_platform=platform,
        update_type=update,
        content_text=text,
        content_hash=_make_hash(competitor, text),
        **kwargs,
    )


# --- clean_text tests ---

def test_strips_html():
    result = clean_text("<p>New <b>ice cream</b> flavor!</p>")
    assert "<" not in result
    assert "ice cream" in result


def test_collapses_whitespace():
    result = clean_text("Hello   \n\n  world   ")
    assert result == "Hello world"


def test_truncates_to_max_chars():
    long = "ice cream " * 200
    result = clean_text(long)
    assert len(result) <= 1000


def test_normalizes_unicode():
    result = clean_text("éàü")  # accented characters
    assert isinstance(result, str)


# --- _is_noise tests ---

def test_noise_too_short():
    assert _is_noise("Hi") is True


def test_noise_hashtag_only():
    assert _is_noise("#icecream #dessert #islamabad") is True


def test_noise_no_food_keywords():
    assert _is_noise("This is a completely unrelated text about politics and sports globally.") is True


def test_not_noise_with_food_keyword():
    assert _is_noise("Baskin Robbins launches new ice cream flavor this summer!") is False


def test_not_noise_review():
    assert _is_noise("The brownie cheesecake here is absolutely delicious, 5 stars!") is False


# --- clean_findings dedup tests ---

def test_dedup_same_content():
    f1 = _make("New chocolate ice cream now available at Baskin Robbins!", "BR")
    f2 = _make("New chocolate ice cream now available at Baskin Robbins!", "BR")
    result = clean_findings([f1, f2])
    assert len(result) == 1


def test_dedup_across_seen_hashes():
    f1 = _make("New chocolate ice cream at Baskin Robbins!", "BR")
    seen = {_make_hash("BR", "New chocolate ice cream at Baskin Robbins!")}
    result = clean_findings([f1], seen_hashes=seen)
    assert len(result) == 0


def test_different_competitors_not_deduped():
    text = "New ice cream cake available this summer season!"
    f1 = _make(text, "BR")
    f2 = _make(text, "Layers")
    result = clean_findings([f1, f2])
    assert len(result) == 2


# --- missing field tolerance ---

def test_missing_date_allowed():
    f = _make("Great new dessert cake deal discount offer at the bakery!", post_date=None)
    result = clean_findings([f])
    assert len(result) == 1
    assert result[0].post_date is None


def test_missing_rating_allowed():
    f = _make("Amazing new menu launch — new flavor ice cream!")
    result = clean_findings([f])
    assert len(result) == 1
    assert result[0].rating is None


def test_missing_url_allowed():
    f = _make("New brownie flavor at dessert bakery sale discount!", source_url=None)
    result = clean_findings([f])
    assert len(result) == 1


# --- normalization ---

def test_engagement_coerced_to_int():
    f = _make(
        "New ice cream summer cake discount deal at bakery!",
        engagement={"likes": "1200", "comments": "45"},
    )
    result = clean_findings([f])
    assert result[0].engagement["likes"] == 1200
    assert result[0].engagement["comments"] == 45


def test_unknown_platform_normalized():
    f = _make("New ice cream summer cake dessert offer!", platform="twitter_x")
    result = clean_findings([f])
    assert result[0].source_platform == "web_search"


def test_unknown_update_type_normalized():
    f = _make("Great dessert brownie cake menu price launch deal!", update="viral_trend")
    result = clean_findings([f])
    assert result[0].update_type == "post"


# --- noise filter ---

def test_pure_emoji_noise_dropped():
    f = _make("🍦🍰🎂✨🎉🍩🧁🍫🍬🍭💕🌟", platform="instagram")
    result = clean_findings([f])
    # After stripping emojis and collapse, the text becomes too short to pass noise filter
    assert len(result) == 0


def test_html_with_valid_content_kept():
    f = _make("<div><h2>Summer Ice Cream Offer!</h2><p>50% off all flavors this weekend at our dessert shop.</p></div>")
    result = clean_findings([f])
    assert len(result) == 1
    assert "<" not in result[0].content_text


# --- sort order ---

def test_dated_findings_before_undated():
    f_no_date = _make("New summer brownie cake dessert deal discount bakery!")
    f_with_date = _make(
        "New summer ice cream flavor launch now available at bakery!",
        post_date=datetime(2026, 6, 1),
    )
    result = clean_findings([f_no_date, f_with_date])
    assert result[0].post_date is not None
