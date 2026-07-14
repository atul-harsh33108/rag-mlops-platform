"""OpenTelemetry setup — exports spans to the OTel collector (→ Langfuse /api/public/otel).

M2: we use OpenLLMetry to auto-instrument the LLM/HTTP clients and the OTel SDK to export
to the collector over OTLP/HTTP. For the LLM gateway (LiteLLM, M3+) use LiteLLM's NATIVE
`otel` callback instead of OpenLLMetry — OpenLLMetry-on-LiteLLM has a known bug for
non-OpenAI providers (openllmetry issue #3167). For Ollama (M1) OpenLLMetry auto-instruments
the OpenAI-compatible calls fine.

Safe no-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
"""

from __future__ import annotations

import os

from app.observability.logging import get_logger

_log = get_logger("otel")
_INITIALIZED = False


def setup_otel() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        _log.info("otel_disabled", reason="OTEL_EXPORTER_OTLP_ENDPOINT unset")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        service_name = os.environ.get("OTEL_SERVICE_NAME", "rag-app")
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
        trace.set_tracer_provider(provider)
        _INITIALIZED = True
        _log.info("otel_enabled", endpoint=endpoint, service=service_name)
    except Exception as e:  # pragma: no cover - optional dependency / config issues
        _log.warning("otel_setup_failed", error=str(e))
