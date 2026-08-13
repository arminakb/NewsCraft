from __future__ import annotations

from fastapi import HTTPException, Request

from app.core.config import settings
from app.security.auth import TEST_ADMIN, SecurityPrincipal


def request_principal(request: Request) -> SecurityPrincipal:
    """Resolve the principal a handler should act as.

    Mutations always arrive with a principal installed by
    ``SecurityAuthorizationMiddleware``; this seam exists so routers that also
    serve reads have exactly one authorization fallback instead of a private
    copy per router.
    """

    principal = getattr(request.state, "security_principal", None)
    if isinstance(principal, SecurityPrincipal):
        return principal
    if settings.app_env == "test":
        return TEST_ADMIN
    if request.method == "GET":
        return SecurityPrincipal("internal_service", "unauthenticated-read", frozenset())
    raise HTTPException(401, detail={"code": "authentication_required"})


__all__ = ["request_principal"]
