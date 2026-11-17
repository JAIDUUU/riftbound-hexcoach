"""Account deletion (issue #21): the signed-in user deletes their own account, and
everything they own goes with it by cascade (backend/accounts.py)."""

from fastapi import APIRouter, Request, Response, status

from backend.api.dependencies import User, collaborators

router = APIRouter(prefix="/account")


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_own_account(user: User, request: Request) -> Response:
    """Deletes the signed-in user's own account. The confirmation step is the frontend's."""
    collaborators(request).delete_account(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
