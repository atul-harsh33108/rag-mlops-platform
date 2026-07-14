"""M7 sampled-eval unit tests (DB/LLM-free): sampling decision + judge-score parsing."""

from __future__ import annotations

from app.evals.sampled import _parse_scores, _should_sample


def test_should_sample_rate_zero_never():
    for _ in range(50):
        assert _should_sample(0.0) is False


def test_should_sample_rate_one_always():
    for _ in range(50):
        assert _should_sample(1.0) is True


def test_parse_scores_clean_json():
    f, r = _parse_scores('{"faithfulness": 0.9, "answer_relevancy": 0.8}')
    assert f == 0.9
    assert r == 0.8


def test_parse_scores_json_wrapped_in_prose():
    raw = 'Here is my assessment:\n{"faithfulness": 0.5, "answer_relevancy": 0.6}\nThanks.'
    f, r = _parse_scores(raw)
    assert f == 0.5
    assert r == 0.6


def test_parse_scores_invalid_returns_none():
    assert _parse_scores("not json at all") == (None, None)
    assert _parse_scores('{"faithfulness": "high"}') == (None, None)


def test_maybe_sample_skips_when_rate_zero():
    # rate 0 => no background task scheduled; no exception, returns None.
    from app.evals.sampled import maybe_sample_and_eval

    maybe_sample_and_eval(
        tenant_id="acme", trace=None, question="q", answer="a", contexts=["c"]
    )  # should not raise
