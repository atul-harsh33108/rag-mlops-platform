"""Production evaluation (M7).

  - sampled: Bernoulli-sample live /chat traffic and run a lightweight LLM-judge
    faithfulness + answer-relevancy score, posted to Langfuse + sampled_evals. This is the
    always-on production quality signal; the full RAGAS suite stays nightly (eval-nightly.yml).

Never blocks or breaks /chat — failures are logged and dropped.
"""

from app.evals.sampled import maybe_sample_and_eval

__all__ = ["maybe_sample_and_eval"]
