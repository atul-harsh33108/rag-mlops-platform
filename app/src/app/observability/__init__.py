"""Observability. M1: structlog JSON logging + a minimal in-process span recorder so
the /chat path is structured for tracing. M2: replace `Tracer` with Langfuse v4
(`from langfuse import observe, get_client`) + OpenLLMetry OTel export to the collector,
pushing cost + RAGAS scores onto each trace.
"""

from app.observability.logging import configure_logging, get_logger
from app.observability.otel import setup_otel
from app.observability.tracer import Tracer

__all__ = ["configure_logging", "get_logger", "setup_otel", "Tracer"]
