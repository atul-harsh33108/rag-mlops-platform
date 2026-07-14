"""Register the RAG system prompt into the MLflow Prompt Registry and point the
`production` alias at it (M3). This is the versioned-prompt workflow:

  1. edit `rag/prompts/rag_system.md`
  2. `task prompt:register`  -> creates a new prompt version + sets `production` alias
  3. the app picks it up within ~60s (alias-based load TTL) — no restart
  4. CI eval gate runs; if faithfulness regresses, the PR is blocked (ADR 0003)

Run: `uv run python -m app.scripts.register_prompt`
Requires MLFLOW_TRACKING_URI to be set (the mlops profile exposes MLflow at :5000).
"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.observability import get_logger

_log = get_logger("register_prompt")
PROMPT_FILE = Path(__file__).resolve().parents[2] / "rag" / "prompts" / "rag_system.md"


def main() -> None:
    s = get_settings()
    if not s.mlflow_tracking_uri:
        raise SystemExit("MLFLOW_TRACKING_URI is not set; start the mlops profile first.")

    import mlflow  # type: ignore

    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    template = PROMPT_FILE.read_text(encoding="utf-8").strip()
    prompt = mlflow.genai.register_prompt(
        name=s.rag_prompt_name,
        template=template,
        commit_message="Register RAG system prompt from rag_system.md",
        tags={"task": "rag", "team": "mlops"},
    )
    mlflow.genai.set_prompt_alias(
        name=s.rag_prompt_name, version=int(prompt.version), alias=s.rag_prompt_alias
    )
    _log.info(
        "prompt_registered",
        name=s.rag_prompt_name,
        version=prompt.version,
        alias=s.rag_prompt_alias,
    )
    print(f"registered '{s.rag_prompt_name}' v{prompt.version} -> alias '{s.rag_prompt_alias}'")


if __name__ == "__main__":
    main()
