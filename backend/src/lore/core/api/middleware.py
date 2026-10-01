"""HTTP hardening and request plumbing (``docs/architecture/security.md`` §2).

Pure ASGI middlewares, outermost first:

1. ``SecurityHeadersMiddleware``: ``nosniff``, ``Referrer-Policy``, ``X-Frame-Options`` on every
   response and the CSP on everything outside ``/api``.
2. ``RequestContextMiddleware``: request id in/out, one access-log line per request, and the
   ``internal_error`` problem for unexpected exceptions (so even those responses carry the id and
   the security headers).
3. ``HostCheckMiddleware``: ``Host`` allowlist against DNS rebinding.
4. ``CORSMiddleware``, only when ``LORE_CORS_ORIGINS`` is set (development).
5. ``MutationGuardMiddleware``: CSRF guard (``X-Lore-Client`` header + ``Origin`` check).
6. ``BodySizeLimitMiddleware``: request bodies are capped at ``MAX_JSON_BODY_BYTES``.
"""

import logging
import re
import time
import uuid
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lore.config import Settings
from lore.core.api.errors import internal_error_response, problem_response
from lore.core.logging import request_id_var

access_logger = logging.getLogger("lore.access")

REQUEST_ID_HEADER = "X-Request-Id"
CLIENT_HEADER = "X-Lore-Client"
ALLOWED_CLIENTS = frozenset({"web", "cli", "test"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_JSON_BODY_BYTES = 10 * 1024 * 1024

# The SPA's Content-Security-Policy. Change it only here, and document why in security.md §2.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}

_INCOMING_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_WILDCARD_BIND_ADDRESSES = frozenset({"0.0.0.0", "[::]", ""})


def normalize_host(value: str) -> str:
    """Lowercase a host name, drop any port, and bracket IPv6 addresses (``[::1]``)."""
    host = value.strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1] if "]" in host else host
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    if ":" in host:  # a bare IPv6 address
        return f"[{host}]"
    return host


def allowed_hosts(settings: Settings) -> frozenset[str]:
    """``LORE_ALLOWED_HOSTS`` plus the configured bind host (unless it binds every interface)."""
    hosts = {normalize_host(host) for host in settings.allowed_hosts}
    bind_host = normalize_host(settings.host)
    if bind_host not in _WILDCARD_BIND_ADDRESSES:
        hosts.add(bind_host)
    return frozenset(hosts)


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, debug: bool = False) -> None:
        self.app = app
        self.debug = debug

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if _INCOMING_REQUEST_ID.fullmatch(incoming) else uuid.uuid7().hex
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            if response_started:
                raise
            response = internal_error_response(exc, debug=self.debug)
            await response(scope, receive, send_with_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            access_logger.info(
                "%s %s %s %.2fms",
                scope["method"],
                scope["path"],
                status,
                duration_ms,
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = _is_api_path(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                if not is_api:
                    headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
            await send(message)

        await self.app(scope, receive, send_with_headers)


class HostCheckMiddleware:
    """Reject requests whose ``Host`` isn't allowed (DNS rebinding). Ports are ignored."""

    def __init__(self, app: ASGIApp, *, hosts: Iterable[str]) -> None:
        self.app = app
        self.hosts = frozenset(hosts)
        self.allow_any = "*" in self.hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.allow_any:
            await self.app(scope, receive, send)
            return
        host = Headers(scope=scope).get("host", "")
        if normalize_host(host) not in self.hosts:
            response = problem_response(
                status=400,
                code="invalid_host",
                title="Invalid host",
                detail="The Host header is not in LORE_ALLOWED_HOSTS.",
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class MutationGuardMiddleware:
    """CSRF guard: mutations need ``X-Lore-Client`` and, if sent, an allowed ``Origin``."""

    def __init__(
        self, app: ASGIApp, *, hosts: Iterable[str], cors_origins: Iterable[str] = ()
    ) -> None:
        self.app = app
        self.hosts = frozenset(hosts)
        self.allow_any = "*" in self.hosts
        self.cors_origins = frozenset(origin.rstrip("/") for origin in cors_origins)

    def _origin_allowed(self, origin: str) -> bool:
        if origin.rstrip("/") in self.cors_origins:
            return True
        parts = urlsplit(origin)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return False
        return self.allow_any or normalize_host(parts.hostname) in self.hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if headers.get(CLIENT_HEADER) not in ALLOWED_CLIENTS:
            response = problem_response(
                status=403,
                code="missing_client_header",
                title="Missing client header",
                detail=f"Requests that change data must send {CLIENT_HEADER}: web or cli.",
            )
            await response(scope, receive, send)
            return
        origin = headers.get("origin")
        if origin is not None and not self._origin_allowed(origin):
            response = problem_response(
                status=403,
                code="bad_origin",
                title="Bad origin",
                detail="The Origin header does not match an allowed host.",
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class _BodyTooLargeError(HTTPException):
    """Raised from ``receive`` once a streamed body passes the limit.

    It is an ``HTTPException`` because FastAPI turns any other error raised while reading the body
    into ``400``. The error handlers map ``413`` to ``payload_too_large``.
    """

    def __init__(self, max_bytes: int) -> None:
        super().__init__(413, f"Request bodies are limited to {max_bytes} bytes.")


class BodySizeLimitMiddleware:
    """Cap request bodies at ``max_bytes`` (declared ``Content-Length`` and streamed bytes).

    ``multipart/form-data`` uploads are exempt here. Upload endpoints enforce
    ``LORE_MAX_UPLOAD_MB`` themselves.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_JSON_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    def _too_large(self) -> ASGIApp:
        return problem_response(
            status=413,
            code="payload_too_large",
            title="Payload too large",
            detail=f"Request bodies are limited to {self.max_bytes} bytes.",
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if headers.get("content-type", "").lower().startswith("multipart/form-data"):
            await self.app(scope, receive, send)
            return
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._too_large()(scope, receive, send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError(self.max_bytes)
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if response_started:
                raise
            await self._too_large()(scope, receive, send)
