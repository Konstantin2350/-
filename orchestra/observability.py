import time

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response


HTTP_REQUESTS = Counter(
    "orchestra_http_requests_total",
    "HTTP requests processed by ИИ-Оркестр",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "orchestra_http_request_duration_seconds",
    "HTTP request duration",
    ("method", "route"),
)
AGENT_RUNS = Counter(
    "orchestra_agent_runs_total",
    "Completed specialist agent runs",
    ("agent", "requires_human"),
)


async def metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    route_object = request.scope.get("route")
    route = getattr(route_object, "path", "unmatched")
    HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    HTTP_DURATION.labels(request.method, route).observe(time.perf_counter() - started)
    return response


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
