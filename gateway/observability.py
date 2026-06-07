import logging
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
import structlog


def setup_observability(service_name: str = "plato-gateway") -> None:
    resource = Resource.create({"service.name": service_name})

    # Traces
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)))
    trace.set_tracer_provider(tp)

    # Metrics
    mp = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint="http://localhost:4317", insecure=True),
                export_interval_millis=10_000,
            )
        ],
    )
    metrics.set_meter_provider(mp)

    # Auto-instrument httpx and asyncpg
    HTTPXClientInstrumentor().instrument()
    AsyncPGInstrumentor().instrument()

    # Structured logging
    logging.basicConfig(level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


tracer = trace.get_tracer("plato-gateway")
meter = metrics.get_meter("plato-gateway")

# Custom metrics
input_tokens_counter = meter.create_counter(
    "plato.tokens.input",
    description="Input tokens consumed",
    unit="tokens",
)
output_tokens_counter = meter.create_counter(
    "plato.tokens.output",
    description="Output tokens generated",
    unit="tokens",
)
ttft_histogram = meter.create_histogram(
    "plato.streaming.ttft",
    description="Time to first token",
    unit="ms",
)
log = structlog.get_logger()