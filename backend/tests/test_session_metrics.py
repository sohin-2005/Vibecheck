from datetime import UTC, datetime, timedelta

from vibecheck.config import ModelPrice
from vibecheck.metrics.session_metrics import (
    UsageRow,
    active_minutes,
    dedupe_usage,
    estimate_cost,
)


def row(mid, model="m", i=1, o=2, cw=0, cr=0):
    return UsageRow(
        api_message_id=mid, model=model, input=i, output=o, cache_write=cw, cache_read=cr
    )


def test_dedupe_keeps_one_row_per_message_id():
    per_model = dedupe_usage([row("a"), row("a"), row("b"), row(None), row(None)])
    assert per_model["m"].input == 4 and per_model["m"].output == 8


def test_cost_sums_models():
    per_model = dedupe_usage([row("a", "x", i=1_000_000, o=0), row("b", "y", i=0, o=2_000_000)])
    prices = {"x": ModelPrice(input=3), "y": ModelPrice(output=15)}
    assert estimate_cost(per_model, prices) == 33.0


def test_cost_none_when_a_used_model_has_no_price():
    per_model = dedupe_usage([row("a", "x"), row("b", "y")])
    assert estimate_cost(per_model, {"x": ModelPrice(input=1)}) is None


def test_cost_ignores_unpriced_models_with_zero_tokens():
    per_model = dedupe_usage([row("a", "x"), row("b", "<synthetic>", i=0, o=0)])
    assert estimate_cost(per_model, {"x": ModelPrice(input=1_000_000)}) == 1.0


def test_active_minutes_excludes_long_gaps():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    ts = [t0, t0 + timedelta(minutes=10), t0 + timedelta(minutes=100), t0 + timedelta(minutes=105)]
    assert active_minutes(ts) == 15.0
    assert active_minutes([]) == 0.0


def test_cost_unknown_without_any_usage_data():
    assert estimate_cost({}, {"x": ModelPrice(input=1)}) is None
    assert (
        estimate_cost(dedupe_usage([row("a", "x", i=0, o=0)]), {"x": ModelPrice(input=1)}) is None
    )
