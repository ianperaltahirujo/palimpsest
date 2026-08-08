"""Local-first security posture.

There is no auth here, deliberately -- see `app.create_app`'s docstring
for the full reasoning. What IS here answers the one threat a loopback,
no-auth server genuinely has: a malicious page open in the same browser
issuing a cross-origin request to `http://127.0.0.1:<port>` and riding
the user's own access to their local files. Two independent checks:

1. `--host` other than loopback requires `--i-know` (enforced in
   `cli.cmd_serve`, not here) -- binding wide open is a decision the
   user must make explicitly, not a default.
2. `OriginCheckMiddleware` below rejects any mutating request whose
   `Origin` header doesn't match an allowed origin. A same-origin
   *navigation* has no `Origin` header at all, but same-origin
   XHR/fetch calls -- which is what the served SPA's own upload/job/
   entities/layout requests are -- DO carry one; browsers do not let a
   page suppress it. That Origin always equals this request's own
   scheme+host+port (from the `Host` header, which a browser sets to
   wherever it actually connected, not something a page can override),
   so same-origin is checked directly against the incoming request
   rather than a precomputed allowlist -- `allowed_origins` only needs
   to cover genuinely CROSS-origin cases, i.e. `--dev`'s Vite port.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: frozenset[str]):
        super().__init__(app)
        self.allowed_origins = allowed_origins

    async def dispatch(self, request: Request, call_next):
        if request.method in _MUTATING_METHODS:
            origin = request.headers.get("origin")
            same_origin = f"{request.url.scheme}://{request.url.netloc}"
            if origin is not None and origin != same_origin and origin not in self.allowed_origins:
                return JSONResponse(
                    {"detail": f"origin {origin!r} not allowed"}, status_code=403
                )
        return await call_next(request)
