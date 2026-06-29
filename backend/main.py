"""FastAPI entry point for CoinDCX Futures Report Studio."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .coindcx_client import CoinDCXAPIError, CoinDCXClient
from .config import FRONTEND_DIR, OUTPUTS_DIR
from .models.schemas import (
    AuthRequest,
    DailyFromReportRequest,
    LogoutRequest,
    MultiTokenReportRequest,
    SingleTokenReportRequest,
)
from .services.export_engine import REPORTS
from .services.report_engine import (
    convert_existing_report_to_daily,
    generate_multi_token_report,
    generate_single_token_report,
)
from .services.transaction_fetcher import TransactionFetchError
from .session_store import SESSIONS
from .utils.file_utils import resolve_safe_report_file


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="CoinDCX Futures Report Studio",
    description="Local, read-only CoinDCX Futures transaction analytics.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; frame-ancestors 'none'"
    )
    return response


def error_response(message: str, status_code: int = 400, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "message": message, "details": details or {}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
        fields.append({"field": location or "request", "message": error.get("msg", "Invalid value")})
    return error_response("Please correct the highlighted request values.", 422, {"fields": fields})


@app.exception_handler(Exception)
async def unexpected_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error: %s", type(exc).__name__)
    return error_response("The report studio hit an unexpected error. Check the server log and try again.", 500)


@app.get("/api/health")
def health() -> dict[str, str]:
    SESSIONS.cleanup_expired()
    return {"status": "ok"}


@app.post("/api/auth/test")
def test_authentication(request: AuthRequest):
    client = CoinDCXClient(request.api_key, request.api_secret)
    try:
        client.get_transactions(
            stage="all",
            page=1,
            size=1,
            margin_currency_short_name=[request.margin_currency],
        )
    except CoinDCXAPIError as exc:
        client.close()
        status_code = 401 if exc.status_code in {401, 403} else 502
        return error_response(f"Authentication failed: {exc}", status_code)
    except Exception as exc:
        client.close()
        logger.warning("Authentication check failed: %s", type(exc).__name__)
        return error_response("Authentication failed. Verify the credentials and network connection.", 502)

    session_id = SESSIONS.create(client)
    return {
        "success": True,
        "session_id": session_id,
        "message": "Authenticated successfully. Credentials are held only in server memory.",
    }


@app.post("/api/auth/logout")
def logout(request: LogoutRequest) -> dict[str, object]:
    removed = SESSIONS.remove(request.session_id)
    return {
        "success": True,
        "message": "Session cleared from memory." if removed else "Session was already cleared or expired.",
    }


def _client_for(session_id: str):
    try:
        return SESSIONS.get_client(session_id)
    except KeyError:
        return None


def _report_error(exc: Exception):
    if isinstance(exc, (ValueError, KeyError)):
        return error_response(str(exc).strip("'"), 400)
    if isinstance(exc, TransactionFetchError):
        return error_response(str(exc), 502)
    if isinstance(exc, CoinDCXAPIError):
        return error_response(str(exc), 502)
    raise exc


@app.post("/api/reports/multi-token")
def multi_token_report(request: MultiTokenReportRequest):
    client = _client_for(request.session_id)
    if client is None:
        return error_response("Session expired. Reconnect your CoinDCX credentials.", 401)
    try:
        return generate_multi_token_report(client, request)
    except Exception as exc:
        return _report_error(exc)


@app.post("/api/reports/single-token")
def single_token_report(request: SingleTokenReportRequest):
    client = _client_for(request.session_id)
    if client is None:
        return error_response("Session expired. Reconnect your CoinDCX credentials.", 401)
    try:
        return generate_single_token_report(client, request)
    except Exception as exc:
        return _report_error(exc)


@app.post("/api/reports/daily-from-report")
def daily_from_report(request: DailyFromReportRequest):
    if _client_for(request.session_id) is None:
        return error_response("Session expired. Reconnect your CoinDCX credentials.", 401)
    try:
        return convert_existing_report_to_daily(
            request.session_id,
            request.report_id,
            request.initial_capital,
            zero_zero_as_funding=request.funding_detection_mode == "parent_type_stage_and_zero_heuristic",
            trade_count_mode=request.trade_count_mode,
        )
    except Exception as exc:
        return _report_error(exc)


@app.get("/api/reports/recent")
def recent_reports(session_id: str = Query(min_length=20, max_length=200)):
    if _client_for(session_id) is None:
        return error_response("Session expired. Reconnect your CoinDCX credentials.", 401)
    return {"success": True, "reports": REPORTS.recent(session_id)}


@app.get("/api/download/{report_id}/{filename}")
def download_report_file(report_id: str, filename: str):
    try:
        path = resolve_safe_report_file(OUTPUTS_DIR, report_id, filename)
    except ValueError as exc:
        return error_response(str(exc), 400)
    if not path.is_file():
        return error_response("Report file not found.", 404)
    media_type = "application/json" if path.suffix.lower() == ".json" else "text/csv; charset=utf-8"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

