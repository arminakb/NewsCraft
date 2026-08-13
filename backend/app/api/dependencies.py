from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.security.application_principal import resolve_application_principal
from app.security.auth import AuthenticationFailure, SecurityPrincipal
from app.security.middleware import MUTATION_METHODS

#: The request-scoped database session, as a parameter default. Routers import
#: this instead of re-deriving ``Depends(get_session)``, so the session seam has
#: exactly one definition to swap when the wiring changes.
SessionDependency = Depends(get_session)

#: The same seam as an annotation, for handlers that prefer ``session:
#: InjectedSession`` over a parameter default.
InjectedSession = Annotated[AsyncSession, Depends(get_session)]

#: Default denial code. The automation surface publishes
#: ``insufficient_permission`` instead (see the policy note next to
#: ``INSUFFICIENT_PERMISSION_PREFIXES`` in ``app.security.middleware``); that
#: router passes its code explicitly so the split stays one visible decision.
SCOPE_DENIED_CODE = "scope_denied"


def authorize_request(
    request: Request,
    *,
    required_scope: str | None,
    mutation: bool,
    denial_code: str = SCOPE_DENIED_CODE,
) -> SecurityPrincipal:
    """Authenticate a request and enforce ``required_scope`` in the handler.

    This is the single in-handler authorization primitive: routers resolve
    through it instead of reading ``request.state`` or calling
    ``resolve_application_principal`` behind their own fallback. ``mutation``
    tells the principal seam whether same-origin proof is required when the
    deployment authenticates the local owner; callers that classify a route
    differently from its HTTP method (a read-only POST, for example) say so
    here rather than growing a private copy of this function.
    """

    try:
        principal = resolve_application_principal(request, config=settings, mutation=mutation)
    except AuthenticationFailure as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None
    if required_scope is not None and not principal.permits(required_scope):
        raise HTTPException(403, detail={"code": denial_code})
    return principal


def request_principal(
    request: Request,
    *,
    read_scope: str | None = None,
    denial_code: str = SCOPE_DENIED_CODE,
) -> SecurityPrincipal:
    """Resolve the principal a handler should act as, classifying by method.

    Mutations arrive with a principal already installed by
    ``SecurityAuthorizationMiddleware``, which also enforced their write scope.
    Reads are not covered by the middleware rule table, so they resolve here
    through the same application-principal seam and — when ``read_scope`` is
    supplied — must actually hold that scope. There is no anonymous fallback:
    an unauthenticated read fails closed exactly like an unauthenticated
    mutation.
    """

    mutation = request.method.upper() in MUTATION_METHODS
    return authorize_request(
        request,
        required_scope=None if mutation else read_scope,
        mutation=mutation,
        denial_code=denial_code,
    )


def principal_dependency(
    read_scope: str | None = None,
    *,
    denial_code: str = SCOPE_DENIED_CODE,
) -> Callable[[Request], SecurityPrincipal]:
    """``Depends`` adapter for :func:`request_principal`.

    FastAPI inspects a dependency's signature, so the scope is bound here
    instead of being exposed as a request parameter.
    """

    def dependency(request: Request) -> SecurityPrincipal:
        return request_principal(request, read_scope=read_scope, denial_code=denial_code)

    return dependency


def scoped_principal_dependency(
    required_scope: str,
    *,
    mutation: bool,
    denial_code: str = SCOPE_DENIED_CODE,
) -> Callable[[Request], SecurityPrincipal]:
    """``Depends`` adapter for :func:`authorize_request`.

    Used by routers whose route classification does not follow the HTTP method
    and which therefore must enforce their scope on every request.
    """

    def dependency(request: Request) -> SecurityPrincipal:
        return authorize_request(
            request,
            required_scope=required_scope,
            mutation=mutation,
            denial_code=denial_code,
        )

    return dependency


__all__ = [
    "SCOPE_DENIED_CODE",
    "InjectedSession",
    "SessionDependency",
    "authorize_request",
    "principal_dependency",
    "request_principal",
    "scoped_principal_dependency",
]
