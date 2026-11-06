import logging
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth.deps import CSRF_HEADER
from app.auth.router import router as auth_router
from app.config import Settings, get_settings
from app.health import router as health_router
from app.messaging.router import router as messaging_router
from app.messaging.ws import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("duo")

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_COMMON_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Cross-Origin-Resource-Policy": "same-origin",
}

# API responses are data only: nothing may load or run from them, and nothing is cached.
_API_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def _site_csp(settings: Settings) -> str:
    """Policy for the website itself: only this origin's scripts, styles and connections."""
    sockets = " ".join(f"wss://{h}" for h in settings.allowed_hosts if h not in ("localhost", "127.0.0.1"))
    return (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        f"font-src 'self'; connect-src 'self' {sockets}; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ).replace("  ", " ")


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        return f"{parts.scheme}://{parts.netloc}"
    return None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Duo API",
        docs_url="/api/docs" if settings.docs_enabled else None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
        redoc_url=None,
    )

    site_csp = _site_csp(settings)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        path = request.url.path
        headers = dict(_COMMON_HEADERS)
        if path.startswith("/api"):
            headers.update(_API_HEADERS)
        else:
            headers["Content-Security-Policy"] = site_csp
            # Built assets have content hashes in their names, so they can be cached forever;
            # the page itself is always revalidated so updates show up immediately.
            headers["Cache-Control"] = (
                "public, max-age=31536000, immutable" if path.startswith("/assets/") else "no-cache"
            )
        if settings.cookie_secure:
            headers["Strict-Transport-Security"] = "max-age=31536000"
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response

    @app.middleware("http")
    async def origin_check(request: Request, call_next):  # type: ignore[no-untyped-def]
        # Defence in depth alongside SameSite cookies and CSRF tokens: state-changing requests
        # must come from a trusted browser origin. This also blocks login CSRF.
        if request.method in _UNSAFE_METHODS and _request_origin(request) not in settings.allowed_origins:
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "Origin not allowed"})
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", CSRF_HEADER],
        max_age=600,
    )
    # Added last so it runs first.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Report which fields failed without echoing submitted values (which may include passwords).
        fields = sorted({".".join(str(p) for p in err.get("loc", ())[1:]) or "body" for err in exc.errors()})
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid request", "fields": fields},
        )

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(messaging_router)
    app.include_router(ws_router)

    # Serve the built website last, so /api routes always take precedence.
    if settings.static_dir:
        static = Path(settings.static_dir)
        if not (static / "index.html").is_file():
            raise RuntimeError(f"STATIC_DIR={static} does not contain index.html")
        app.mount("/", StaticFiles(directory=static, html=True), name="site")
    return app


app = create_app()
