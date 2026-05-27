"""
Role-Based Access Control (RBAC) — AUDIT-056 fix.

V11.1 bug: All API endpoints were unprotected — any authenticated user
could call expert-only mutation endpoints (e.g. approve_claim, delete_bottleneck).

V11.2 fix:
- @require_role("expert"|"viewer"|"admin") FastAPI decorator
- Pilot mode: mock auth (no real OAuth2 server needed for development)
- Production mode: OAuth2 JWT compatible (Bearer token validation)
- Unauthorized request → HTTP 403 Forbidden

Role hierarchy:
  admin  > expert > viewer
  admin  : full access (read + write + delete + admin ops)
  expert : read + write (can approve claims, edit bottlenecks)
  viewer : read only (cannot mutate)

Usage:
    from echelon.core.rbac import require_role

    @router.post("/claims/approve")
    @require_role("expert")
    async def approve_claim(claim_id: str, request: Request):
        ...
"""
from __future__ import annotations

import functools
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 1,
    "expert": 2,
    "admin":  3,
}

VALID_ROLES = frozenset(ROLE_HIERARCHY)

# ---------------------------------------------------------------------------
# Pilot mode: mock token → role mapping
# ---------------------------------------------------------------------------

# [AUDIT-056] In Pilot mode there is no real OAuth2 server.
# These fixed tokens are used for development and integration testing ONLY.
# In production, replace with proper JWT validation.
PILOT_TOKEN_ROLES: dict[str, str] = {
    "pilot-admin-token":  "admin",
    "pilot-expert-token": "expert",
    "pilot-viewer-token": "viewer",
}

# Set PILOT_MODE = True to use the mock token mapping
# Production: set to False and implement resolve_role_from_token()
PILOT_MODE: bool = True


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------

class AuthError(Exception):
    """Raised when a request cannot be authenticated or authorized."""
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


def resolve_role_from_token(token: Optional[str]) -> Optional[str]:
    """
    Resolve a Bearer token to a role string.

    [AUDIT-056] Pilot mode: uses PILOT_TOKEN_ROLES mock mapping.
    Production: replace this function with real JWT validation.

    Args:
        token: Bearer token from Authorization header (without "Bearer " prefix).

    Returns:
        Role string ("admin"|"expert"|"viewer") or None if token is invalid.
    """
    if token is None:
        return None

    if PILOT_MODE:
        return PILOT_TOKEN_ROLES.get(token)

    # Production stub — replace with real JWT decode + role claim extraction
    # Example (using python-jose):
    #   payload = jose.jwt.decode(token, settings.JWT_PUBLIC_KEY, algorithms=["RS256"])
    #   return payload.get("role")
    logger.warning("[AUDIT-056] Production JWT validation not implemented; rejecting token")
    return None


def get_token_from_request(request: object) -> Optional[str]:
    """
    Extract Bearer token from a FastAPI Request object.

    Falls back to checking a 'X-Pilot-Token' header for simplified Pilot testing.

    Args:
        request: FastAPI Request (or any object with .headers dict-like attribute).

    Returns:
        Token string or None.
    """
    headers = getattr(request, "headers", {})

    # Standard: Authorization: Bearer <token>
    auth_header = headers.get("Authorization") or headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):]

    # Pilot convenience header (no-op in production)
    pilot_token = headers.get("X-Pilot-Token") or headers.get("x-pilot-token")
    if pilot_token:
        return pilot_token

    return None


# ---------------------------------------------------------------------------
# RBAC decorator  [AUDIT-056]
# ---------------------------------------------------------------------------

def require_role(minimum_role: str) -> Callable:
    """
    [AUDIT-056] FastAPI-compatible RBAC decorator.

    Wraps an endpoint function to enforce role-based access control.
    Unauthorized callers receive HTTP 403 (raised as AuthError).

    Role hierarchy (ascending privilege):
        viewer (1) → expert (2) → admin (3)

    Args:
        minimum_role: The minimum role required to access the endpoint.
                      One of "viewer", "expert", "admin".

    Returns:
        Decorator that wraps the endpoint function.

    Example:
        @router.post("/claims/{claim_id}/approve")
        @require_role("expert")
        async def approve_claim(claim_id: str, request: Request):
            ...
    """
    if minimum_role not in VALID_ROLES:
        raise ValueError(
            f"[AUDIT-056] Invalid role {minimum_role!r}. "
            f"Valid roles: {sorted(VALID_ROLES)}"
        )

    required_level = ROLE_HIERARCHY[minimum_role]

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Find the 'request' argument (FastAPI injects it)
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if hasattr(arg, "headers"):
                        request = arg
                        break

            if request is None:
                raise AuthError(
                    f"[AUDIT-056] No request object found; cannot authenticate. "
                    f"Endpoint requires role '{minimum_role}'.",
                    status_code=403,
                )

            token = get_token_from_request(request)
            role = resolve_role_from_token(token)

            if role is None:
                raise AuthError(
                    f"[AUDIT-056] Missing or invalid authentication token. "
                    f"Endpoint requires role '{minimum_role}'.",
                    status_code=401,
                )

            caller_level = ROLE_HIERARCHY.get(role, 0)
            if caller_level < required_level:
                raise AuthError(
                    f"[AUDIT-056] Access denied: role '{role}' (level={caller_level}) "
                    f"cannot access endpoint requiring '{minimum_role}' (level={required_level}).",
                    status_code=403,
                )

            logger.debug(
                f"[AUDIT-056] Access granted: role='{role}' → endpoint requires '{minimum_role}'"
            )
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Sync variant for testing without async
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if hasattr(arg, "headers"):
                        request = arg
                        break

            if request is None:
                raise AuthError(
                    f"[AUDIT-056] No request object found; cannot authenticate.",
                    status_code=403,
                )

            token = get_token_from_request(request)
            role = resolve_role_from_token(token)

            if role is None:
                raise AuthError(
                    f"[AUDIT-056] Missing or invalid authentication token.",
                    status_code=401,
                )

            caller_level = ROLE_HIERARCHY.get(role, 0)
            if caller_level < required_level:
                raise AuthError(
                    f"[AUDIT-056] Access denied: role '{role}' cannot access "
                    f"endpoint requiring '{minimum_role}'.",
                    status_code=403,
                )

            return func(*args, **kwargs)

        # Return the appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# Standalone auth check (for use outside decorators)
# ---------------------------------------------------------------------------

def check_role(request: object, minimum_role: str) -> str:
    """
    Imperative role check — call directly inside a function body.

    [AUDIT-056] Alternative to the @require_role decorator for cases where
    role logic depends on request body content (not just the endpoint).

    Args:
        request:      FastAPI Request or mock with .headers attribute.
        minimum_role: Minimum required role.

    Returns:
        The caller's actual role string.

    Raises:
        AuthError: If token is missing, invalid, or insufficient role.
    """
    if minimum_role not in VALID_ROLES:
        raise ValueError(f"[AUDIT-056] Invalid minimum_role: {minimum_role!r}")

    required_level = ROLE_HIERARCHY[minimum_role]
    token = get_token_from_request(request)
    role = resolve_role_from_token(token)

    if role is None:
        raise AuthError("[AUDIT-056] Missing or invalid token", status_code=401)

    caller_level = ROLE_HIERARCHY.get(role, 0)
    if caller_level < required_level:
        raise AuthError(
            f"[AUDIT-056] Access denied: role='{role}' requires '{minimum_role}'.",
            status_code=403,
        )

    return role
