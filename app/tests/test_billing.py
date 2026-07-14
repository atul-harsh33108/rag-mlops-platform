"""M7 billing unit tests (DB-free): plans, metering math, budget-cap response shape."""

from __future__ import annotations

import pytest

from app.billing.meter import compute_cost, estimate_tokens
from app.billing.plans import DEFAULT_PLAN, PLAN, get_plan
from app.billing.spend import BudgetExceeded


def test_get_plan_defaults():
    assert get_plan(None).name == DEFAULT_PLAN
    assert get_plan("nope").name == DEFAULT_PLAN
    assert get_plan("pro").name == "pro"


def test_plan_tiers_monotonic():
    # enterprise >= pro >= free on both rate limit and budget
    assert (
        PLAN["enterprise"].rate_limit_per_minute
        > PLAN["pro"].rate_limit_per_minute
        > PLAN["free"].rate_limit_per_minute
    )
    assert (
        PLAN["enterprise"].monthly_budget_usd
        >= PLAN["pro"].monthly_budget_usd
        >= PLAN["free"].monthly_budget_usd
    )


def test_estimate_tokens_positive():
    assert estimate_tokens("") >= 1
    assert estimate_tokens("a" * 40) == 10
    assert estimate_tokens("hello world") >= 1


def test_compute_cost_known_model():
    # qwen3:14b: 0.0007/1k in, 0.0014/1k out
    cost = compute_cost("qwen3:14b", prompt_tokens=1000, completion_tokens=1000)
    assert cost == pytest.approx(0.0007 + 0.0014, rel=1e-6)


def test_compute_cost_unknown_model_uses_default():
    cost = compute_cost("some-unknown-model", 1000, 1000)
    # default (0.001, 0.002)
    assert cost == pytest.approx(0.001 + 0.002, rel=1e-6)


def test_budget_exceeded_carries_upgrade_fields():
    exc = BudgetExceeded("acme", spent=12.34, cap=10.0, plan="free")
    assert exc.tenant_id == "acme"
    assert exc.spent == 12.34
    assert exc.cap == 10.0
    assert exc.plan == "free"
    assert "over monthly budget" in str(exc)


def test_budget_exceeded_response_is_429_with_upgrade():
    from app.api.chat import _budget_exceeded_response

    exc = BudgetExceeded("acme", spent=12.0, cap=10.0, plan="free")
    resp = _budget_exceeded_response(exc)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "3600"
    body = __import__("json").loads(resp.body)
    assert body["detail"] == "monthly budget exceeded"
    assert body["plan"] == "free"
    assert "upgrade" in body  # the upgrade prompt
    assert body["cap_usd"] == 10.0
