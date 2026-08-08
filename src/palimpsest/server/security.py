"""Local-first security posture.

There is no auth here, deliberately -- see `app.create_app`'s docstring
for the full reasoning. What IS here answers the two threats a loopback,
no-auth server genuinely has: (1) a malicious page open in another
browser tab issuing a cross-origin request to `http://127.0.0.1:<port>`
and riding the user's own access to their local files, and (2) since
`extra_origins` can now legitimately include a public HTTPS origin (a
GitHub Pages URL serving a standalone build of this same frontend --
see `PUT /api/keys` in `routes.py`), a browser's own Private Network
Access check standing between that public origin and this loopback
target.

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
   `--allow-origin` the caller explicitly named. This must never
   include a wildcard -- that would let ANY webpage the user happens
   to have open drive this server, not just the one(s) intended.
3. `PrivateNetworkAccessMiddleware` below answers the extra preflight
   check Chrome performs before a request from a public, non-private
   origin is allowed to reach a private-network/loopback target at
   all -- independent of, and in addition to, ordinary CORS. Without
   it, a correctly-configured `--allow-origin`/CORS setup still fails
   in Chrome for exactly the GitHub-Pages-to-localhost case this exists
   for. Only ever installed alongside `CORSMiddleware`, i.e. only when
   `extra_origins` is non-empty (see `app.create_app`) -- there is
   nothing to answer when every request is same-origin.
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


class PrivateNetworkAccessMiddleware(BaseHTTPMiddleware):
    """Chrome requires a server to opt in via
    `Access-Control-Allow-Private-Network: true` on a CORS preflight
    before a request from a public origin to a loopback/private target
    (this server) is allowed to proceed -- Starlette's `CORSMiddleware`
    doesn't send this header on its own. Must be added to the app AFTER
    `CORSMiddleware` (Starlette wraps outermost = last-added), so it
    runs around it and can add the header to the preflight response
    `CORSMiddleware` already produced, rather than trying to build a
    preflight response itself."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if (
            request.method == "OPTIONS"
            and request.headers.get("access-control-request-private-network") == "true"
        ):
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response
