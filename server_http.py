import os
import secrets

import uvicorn
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp.server.transport_security import TransportSecuritySettings
from server import mcp


class RequireBearerToken:
    """Protect HTTP requests while forwarding ASGI lifecycle events."""

    def __init__(self, app, token):
        self.app = app
        self.expected = b"Bearer " + token.encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        public_health = (
            scope["path"] == "/health"
            and scope["method"] in {"GET", "HEAD"}
        )
        if not public_health:
            values = [
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"authorization"
            ]
            authorized = (
                len(values) == 1
                and secrets.compare_digest(values[0], self.expected)
            )
            if not authorized:
                response = JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                    headers={
                        "WWW-Authenticate": "Bearer",
                        "Cache-Control": "no-store",
                    },
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


async def health(request):
    return JSONResponse({"status": "ok"})


def build_app():
    token = os.environ.get("MAPCP_API_TOKEN", "")
    if len(token) < 32 or not token.isascii() or any(
        character.isspace() for character in token
    ):
        raise RuntimeError(
            "Set MAPCP_API_TOKEN to a secret ASCII token of at least "
            "32 characters, without whitespace."
        )

    allowed_hosts = [
        value.strip()
        for value in os.environ.get(
            "MAPCP_ALLOWED_HOSTS",
            "127.0.0.1,127.0.0.1:*,localhost,localhost:*",
        ).split(",")
        if value.strip()
    ]
    if not allowed_hosts or "*" in allowed_hosts:
        raise RuntimeError(
            "Configure explicit MAPCP_ALLOWED_HOSTS; a bare wildcard "
            "is not permitted."
        )

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
        ],
    )
    http_app = mcp.streamable_http_app(transport_security=security)
    http_app.routes.insert(
        0, Route("/health", health, methods=["GET", "HEAD"])
    )
    return RequireBearerToken(http_app, token)


def main():
    host = os.environ.get("MAPCP_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    if not 1 <= port <= 65535:
        raise RuntimeError("PORT must be between 1 and 65535.")

    uvicorn.run(build_app(), host=host, port=port, workers=1)


if __name__ == "__main__":
    main()
