"""Unit tests for chat_response_guard price-claim stripping.

These tests cover the post-sampling guard that prevents the assistant
from emitting specific price assertions when no trade listing was produced.

Note: This file is intentionally self-contained. It tests pure-Python logic
in `chat_response_guard.py` and does NOT require:
- a database connection
- the FastAPI TestClient
- any fixture from `conftest.py`

Reason: Sprint 1 Phase 1a (暮鼓) is building `tests/` infrastructure.
This module can land immediately and will be kept when Phase 1a completes.
Later Phase 1b-4 may add integration/end-to-end guard tests on top.
"""

from app.services.chat_response_guard import (
    has_listing_price_in_turn,
    strip_ungrounded_price_claims,
)


class TestHasListingPriceInTurn:
    def test_zero_events_returns_false(self):
        assert has_listing_price_in_turn(0) is False

    def test_positive_count_returns_true(self):
        assert has_listing_price_in_turn(1) is True
        assert has_listing_price_in_turn(5) is True


class TestStripUngroundedPriceClaims:
    # ── Baseline: had_listing=True → never modify ──

    def test_had_listing_true_with_price_assertion(self):
        text = "这件装备大概值 3-5 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=True)
        assert result == text

    def test_had_listing_true_without_price_assertion(self):
        text = "这件装备很强"
        result = strip_ungrounded_price_claims(text, had_listing=True)
        assert result == text

    # ── had_listing=False, no price assertion → pass through ──

    def test_no_listing_no_assertion(self):
        text = "这件装备很强，但没有在售标价"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert result == text

    def test_empty_text(self):
        assert strip_ungrounded_price_claims("", had_listing=False) == ""

    # ── had_listing=False, price assertion present → hard replace ──

    def test_simple_price_with_currency(self):
        text = "市价大约 3 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert result != text
        assert "[价格需市集查询确认]" in result
        assert "3 崇高" not in result

    def test_price_range_with_tilde(self):
        text = "估计 3~8 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result
        assert "3~8 崇高" not in result

    def test_price_range_with_chinese_tilde(self):
        text = "大概 3～8 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_range_with_dash(self):
        text = "建议 3-5 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_range_with_to(self):
        text = "参考 3 到 8 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_divine(self):
        text = "这件装备值 2 神圣"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_chaos(self):
        text = "大概 50 混沌"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_ex(self):
        text = "估计 1.5 ex"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_e_uppercase(self):
        text = "大概 2 E"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_d_uppercase(self):
        text = "大概 3 D"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_explicit_prefix(self):
        text = "售价为 100 混沌"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_quote_prefix(self):
        text = "报价约 5 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_market_prefix(self):
        text = "市价为 3 神圣"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_value_prefix(self):
        text = "值 10 exalted"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    def test_price_with_decimal(self):
        text = "大概 1.5 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "[价格需市集查询确认]" in result

    # ── No false positives ──

    def test_number_without_currency_not_triggered(self):
        text = "这把武器有 500 点 DPS"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert result == text

    def test_plain_chinese_number_not_triggered(self):
        text = "需要 3 个技能宝石"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert result == text

    def test_item_level_not_triggered(self):
        text = "物等 82 的项链"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert result == text

    # ── Hard replacement sanity ──

    def test_multiple_price_claims_all_replaced(self):
        text = "大概 3 崇高，估计 5-8 神圣"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert result == "[价格需市集查询确认]，[价格需市集查询确认]"

    def test_replacement_does_not_contain_original_numbers(self):
        text = "这件装备大概值 3-5 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "3" not in result
        assert "5" not in result
        assert "崇高" not in result
