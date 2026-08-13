from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request

from app.core.config import settings
from app.security.application_principal import resolve_application_principal
from app.security.auth import AuthenticationFailure, SecurityPrincipal
from app.security.middleware import MUTATION_METHODS


def request_principal(request: Request, *, read_scope: str | None = None) -> SecurityPrincipal:
    """Resolve the principal a handler should act as.

    Mutations arrive with a principal already installed by
    ``SecurityAuthorizationMiddleware``, which also enforced their write scope.
    Reads are not covered by the middleware rule table, so they resolve here
    through the same application-principal seam and — when ``read_scope`` is
    supplied — must actually hold that scope. There is no anonymous fallback:
    an unauthenticated read fails closed exactly like an unauthenticated
    mutation.
    """

    mutation = request.method.upper() in MUTATION_METHODS
    try:
        principal = resolve_application_principal(request, config=settings, mutation=mutation)
    except AuthenticationFailure as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None
    if not mutation and read_scope is not None and not principal.permits(read_scope):
        raise HTTPException(403, detail={"code": "scope_denied"})
    return principal


def principal_dependency(read_scope: str | None = None) -> Callable[[Request], SecurityPrincipal]:
    """``Depends`` adapter for :func:`request_principal`.

    FastAPI inspects a dependency's signature, so the scope is bound here
    instead of being exposed as a request parameter.
    """

    def dependency(request: Request) -> SecurityPrincipal:
        return request_principal(request, read_scope=read_scope)

    return dependency


__all__ = ["principal_dependency", "request_principal"]
