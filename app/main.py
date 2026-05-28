import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.enforcement import router as enforcement_router
from app.api.policies import router as policies_router
from app.api.proxy import router as proxy_router
from app.api.routes import router as api_router
from app.core.config import settings
from app.core.limiter import limiter
from app.core.exceptions import AppException
from app.core.logging import get_logger, log_request, setup_logging
from app.middleware import PolicyEnforcementMiddleware
from app.plugins.plugin_loader import load_plugins

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown (community edition)."""
    setup_logging()
    logger.info(
        "Valo Community Edition starting enforcement_mode=%s",
        settings.enforcement_mode,
    )
    plugin_registry = load_plugins()
    app.state.plugins = plugin_registry
    logger.info("Loaded %d plugin(s)", len(plugin_registry))
    yield
    logger.info("Valo Community Edition shutting down")


app = FastAPI(
    title="Valo Community Edition API",
    description=(
        "Open-source Valo: deterministic prompt-injection risk analysis, "
        "YAML governance policies, and monitor-mode AI Firewall proxy."
    ),
    version="0.1.0-community",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(api_router)
app.include_router(policies_router)
app.include_router(proxy_router)
app.include_router(enforcement_router)

app.add_middleware(PolicyEnforcementMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    log_request(logger, request.method, request.url.path)
    return await call_next(request)


def _app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    logger.warning(
        "Application error: %s (status=%d)",
        exc.message,
        exc.status_code,
        extra={"detail": exc.detail},
    )
    error_code = getattr(exc, "code", None) or exc.__class__.__name__
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": error_code,
                "message": exc.message,
                "detail": exc.detail,
            }
        },
    )


def _generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "InternalServerError",
                "message": "An unexpected error occurred",
                "detail": {},
            }
        },
    )


app.add_exception_handler(AppException, _app_exception_handler)
app.add_exception_handler(Exception, _generic_exception_handler)
