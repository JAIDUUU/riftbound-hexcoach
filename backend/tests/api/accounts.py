"""Account deletion for API tests: a recorder, and one that must never run."""

import uuid


class FakeAccounts:
    """Records which Supabase Auth users were deleted."""

    def __init__(self) -> None:
        self.deleted: list[uuid.UUID] = []

    def delete(self, user_id: uuid.UUID) -> None:
        self.deleted.append(user_id)


def unused_account_deletion(user_id: uuid.UUID) -> None:
    raise AssertionError("this test never deletes an account")
