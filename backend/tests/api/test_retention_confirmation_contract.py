from __future__ import annotations

from typing import get_args

from app.api.operations import RetentionRunCreateIn
from app.retention.contracts import RETENTION_CONFIRMATION, RetentionConfirmationPhrase


def test_router_confirmation_literal_comes_from_the_retention_constant() -> None:
    """The router must accept exactly the phrase the service enforces.

    Two independent spellings would let the constant drift, so the router
    rejects the new phrase with a 422 before the service is ever reached.
    """
    annotation = RetentionRunCreateIn.model_fields["confirmation"].annotation
    assert annotation is RetentionConfirmationPhrase
    assert get_args(RetentionConfirmationPhrase.__value__) == (RETENTION_CONFIRMATION,)
