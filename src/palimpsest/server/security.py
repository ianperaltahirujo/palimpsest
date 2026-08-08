"""Local-first security posture.

There is no auth here, deliberately -- see `app.create_app`'s docstring
for the full reasoning. What IS here answers the threat a loopback,
no-auth server genuinely has: a malicious page open in another browser
tab issuing a cross-origin request to `http://127.0.0.1:<port>` and
riding the user's own access to their local files.

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
   to cover genuinely CROSS-origin cases: `--dev`'s Vite port, and any
   `--allow-origin` the caller explicitly named (e.g. a GitHub Pages URL
   hosting a standalone frontend build -- see `PUT /api/keys` in
   `routes.py`). This must never include a wildcard -- that would let
   ANY webpage the user happens to have open drive this server, not
   just the one(s) intended.

A public HTTPS origin reaching a loopback target also needs Chrome's
Private Network Access preflight to succeed, independent of ordinary
CORS -- handled by `app.create_app` passing `allow_private_network=True`
to Starlette's own `CORSMiddleware` (native support, not something this
module implements) whenever `extra_origins` is non-empty. Without it,
Starlette's `CORSMiddleware` treats that preflight as a FAILURE and
returns 400 even with `--allow-origin`/CORS otherwise configured
correctly -- verified against a real server with a real curl preflight,
not just by reading Starlette's source.
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
