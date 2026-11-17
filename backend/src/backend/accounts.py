"""Account deletion (issue #21): deleting the Supabase Auth user is the whole job.

Everything the player owns hangs off `auth.users` with `ON DELETE CASCADE` (conversations
and their messages, decks), and so do Supabase Auth's own rows (identities, sessions and
through them refresh tokens, MFA factors). The backend's database role can delete from
`auth.users` directly, which Supabase documents as supported; its Admin API's hard delete
runs the same `DELETE` plus an audit-log entry. Doing it here keeps the backend free of a
service-role secret.

Access tokens already issued stay valid until they expire: they are stateless JWTs.
"""

import uuid

from sqlalchemy import Connection, text


def delete_account(connection: Connection, user_id: uuid.UUID) -> None:
    """Deletes the user and, by cascade, everything they own. A user who is already gone
    is not an error, so a retried request still succeeds."""
    connection.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": user_id})
