"""
Authentication, authorisation and rate limiting.

The nine controls from the project report, implemented:

  1. Fail-closed authentication — no Supabase, no access. There is no mock
     identity path and no development bypass.
  2. Bearer-token verification against Supabase Auth.
  3. Optional service API key compared with hmac.compare_digest.
  4. Per-identity in-memory rate limiting.
  5. Strict chain allowlist (schemas.py).
  6. Restricted configurable CORS (main.py).
  7. Active-officer check on every authenticated request.
  8. Admin-only dossier review (routers/dossier.py).
  9. Server-derived audit actor identity (services/audit.py).
"""
from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

log = logging.getLogger("chakravyuh.security")

bearer = HTTPBearer(auto_error=False)

Role = Literal["viewer", "analyst", "investigator", "admin"]
_RANK: dict[str, int] = {"viewer": 1, "analyst": 2, "investigator": 3, "admin": 4}


@dataclass(frozen=True)
class Officer:
    """The authenticated principal. Never constructed from client input."""
    id: str
    email: str | None
    role: Role
    is_service: bool = False

    @property
    def rank(self) -> int:
        return _RANK.get(self.role, 0)


# =====================================================================
# Token verification
# =====================================================================
class _TokenCache:
    """
    Short TTL cache for verified tokens.

    Without it, every request costs a round trip to Supabase Auth, and a
    multi-hop trace would be dominated by auth latency. 60 seconds is short
    enough that a revoked session stops working promptly.
    """

    def __init__(self, ttl: int = 60):
        self.ttl = ttl
        self._data: dict[str, tuple[Officer, float]] = {}

    def get(self, token: str) -> Officer | None:
        hit = self._data.get(token)
        if not hit:
            return None
        officer, ts = hit
        if time.monotonic() - ts > self.ttl:
            self._data.pop(token, None)
            return None
        return officer

    def put(self, token: str, officer: Officer) -> None:
        if len(self._data) > 5_000:          # bound memory
            self._data.clear()
        self._data[token] = (officer, time.monotonic())

    def clear(self) -> None:
        self._data.clear()


_token_cache = _TokenCache()


async def _verify_supabase_token(token: str, cfg: Settings) -> Officer:
    """
    Validate a JWT against Supabase Auth, then read the officer's role.

    We call Supabase's /auth/v1/user rather than verifying the JWT signature
    locally. It costs a round trip but it honours revocation: a locally
    verified JWT keeps working until it expires even after the session is
    killed, which is the wrong behaviour for an investigation platform.
    """
    cached = _token_cache.get(token)
    if cached:
        return cached

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(
                f"{cfg.supabase_url}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": cfg.supabase_anon_key},
            )
        except httpx.HTTPError as e:
            log.error("Supabase Auth unreachable: %s", e)
            # Fail CLOSED. An auth service we cannot reach is not permission
            # to let the request through.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "authentication service unavailable",
            )

        if res.status_code != 200:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")

        user = res.json()
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token carries no subject")

        # role comes from the DB, never from the token's own claims —
        # a client-supplied role claim is an escalation waiting to happen
        role: Role = "viewer"
        active = False
        try:
            r = await client.get(
                f"{cfg.supabase_url}/rest/v1/user_roles",
                params={"user_id": f"eq.{user_id}", "select": "role"},
                headers={
                    "apikey": cfg.supabase_service_role_key or cfg.supabase_anon_key,
                    "Authorization":
                        f"Bearer {cfg.supabase_service_role_key or token}",
                },
            )
            if r.status_code == 200 and r.json():
                role = r.json()[0].get("role", "viewer")
                active = True
        except httpx.HTTPError as e:
            log.error("role lookup failed for %s: %s", user_id, e)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "role service unavailable"
            )

        # Control 7: an authenticated user with no officer record is not an
        # officer. Authentication is not authorisation.
        if not active:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "no active officer record for this account",
            )

        officer = Officer(id=user_id, email=user.get("email"), role=role)
        _token_cache.put(token, officer)
        return officer


def _verify_service_key(presented: str, cfg: Settings) -> Officer | None:
    """
    Control 3: constant-time comparison.

    `==` on secrets leaks length and prefix through timing. compare_digest
    does not. The guard on has_service_key also refuses a too-short key
    outright rather than pretending it is configured.
    """
    if not cfg.has_service_key:
        return None
    if hmac.compare_digest(presented, cfg.service_api_key or ""):
        return Officer(id="service", email=None, role="admin", is_service=True)
    return None


# =====================================================================
# Rate limiting
# =====================================================================
class RateLimiter:
    """
    Sliding-window limiter, per identity.

    In-memory, so it is per-process. That is honest for a single-instance
    deployment and documented as such; behind multiple workers you want
    Redis. It is still worth having: it stops one officer's runaway script
    from exhausting the free-tier provider quota for everyone.
    """

    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, identity: str, limit: int, window: int) -> tuple[bool, int, float]:
        now = time.monotonic()
        q = self._hits[identity]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            retry_after = window - (now - q[0])
            return False, 0, max(retry_after, 0.1)
        q.append(now)
        if len(self._hits) > 10_000:
            self._prune(now, window)
        return True, limit - len(q), 0.0

    def _prune(self, now: float, window: int) -> None:
        for k in [k for k, v in self._hits.items() if not v or now - v[-1] > window * 2]:
            self._hits.pop(k, None)

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


# =====================================================================
# Dependencies
# =====================================================================
async def get_current_officer(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    cfg: Settings = Depends(get_settings),
) -> Officer:
    """Control 1 + 2 + 3: the only way to obtain an identity."""
    api_key = request.headers.get("x-api-key")
    if api_key:
        svc = _verify_service_key(api_key, cfg)
        if svc:
            request.state.officer = svc
            return svc
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid service key")

    if creds is None or not creds.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    officer = await _verify_supabase_token(creds.credentials, cfg)
    request.state.officer = officer
    request.state.access_token = creds.credentials
    return officer


def require_role(minimum: Role):
    """Dependency factory: refuse anyone below `minimum`."""
    async def _dep(
        officer: Officer = Depends(get_current_officer),
    ) -> Officer:
        if officer.rank < _RANK[minimum]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"role '{minimum}' or higher required (you are '{officer.role}')",
            )
        return officer
    return _dep


def rate_limit(limit: int | None = None, window: int | None = None, bucket: str = "default"):
    """Control 4: per-identity, per-bucket limiting."""
    async def _dep(
        request: Request,
        officer: Officer = Depends(get_current_officer),
        cfg: Settings = Depends(get_settings),
    ) -> Officer:
        lim = limit or cfg.rate_limit_requests
        win = window or cfg.rate_limit_window_seconds
        allowed, remaining, retry = limiter.check(f"{bucket}:{officer.id}", lim, win)
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"rate limit exceeded: {lim} requests per {win}s",
                headers={"Retry-After": str(int(retry) + 1)},
            )
        request.state.rate_remaining = remaining
        return officer
    return _dep
