"""Account deletion against Postgres (issue #21): only the real database can prove the cascades."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Connection, func, select, text

from backend.accounts import delete_account
from backend.conversations.limits import Limits
from backend.conversations.schema import messages_table
from backend.conversations.store import SqlConversationStore
from backend.decks.store import SqlDeckStore

pytestmark = pytest.mark.integration


# Every foreign key in `public` on a path to auth.users: those pointing at it directly,
# then those pointing at a table already found, and so on.
_PATHS_TO_AUTH_USERS = text(
    """
    WITH RECURSIVE owned (table_oid, table_name, constraint_name, on_delete) AS (
        SELECT c.conrelid, t.relname::text, c.conname::text, c.confdeltype::text
        FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        WHERE c.contype = 'f' AND c.confrelid = 'auth.users'::regclass
          AND t.relnamespace = 'public'::regnamespace
        UNION
        SELECT c.conrelid, t.relname::text, c.conname::text, c.confdeltype::text
        FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        JOIN owned o ON c.confrelid = o.table_oid
        WHERE c.contype = 'f' AND t.relnamespace = 'public'::regnamespace
    )
    SELECT table_name, constraint_name, on_delete FROM owned
    """
)

_AUTH_FOREIGN_KEYS = text(
    "SELECT conrelid::regclass::text, confrelid::regclass::text, confdeltype::text "
    "FROM pg_constraint WHERE contype = 'f' AND connamespace = 'auth'::regnamespace"
)


def test_every_table_that_hangs_off_a_user_is_deleted_with_them(
    db_connection: Connection,
) -> None:
    paths = db_connection.execute(_PATHS_TO_AUTH_USERS).all()

    assert {"conversations", "messages", "decks"} <= {table for table, _, _ in paths}
    # 'c' is ON DELETE CASCADE. Anything else either blocks the deletion or leaves rows behind.
    assert [(table, name) for table, name, on_delete in paths if on_delete != "c"] == []


def test_supabase_auths_own_sign_in_rows_are_deleted_with_the_user(
    db_connection: Connection,
) -> None:
    foreign_keys = {tuple(row) for row in db_connection.execute(_AUTH_FOREIGN_KEYS)}

    assert {
        ("auth.identities", "auth.users", "c"),
        ("auth.sessions", "auth.users", "c"),
        ("auth.refresh_tokens", "auth.sessions", "c"),
    } <= foreign_keys


def _auth_user_exists(connection: Connection, user_id: uuid.UUID) -> bool:
    found = connection.execute(text("SELECT 1 FROM auth.users WHERE id = :id"), {"id": user_id})
    return found.first() is not None


def test_deleting_an_account_removes_the_user_and_everything_they_own(
    db_connection: Connection, new_auth_user: Callable[[], uuid.UUID]
) -> None:
    conversations = SqlConversationStore(db_connection, Limits())
    decks = SqlDeckStore(db_connection)
    alice, bob = new_auth_user(), new_auth_user()
    chat = conversations.create(alice, "Sona timing")
    conversations.add_message(alice, chat.id, "user", "Does Sona trigger on a move?")
    deck = decks.create(alice, "Annie burn", "Legend:\n1 Annie, Dark Child\n")
    bobs_chat = conversations.create(bob, None)
    conversations.add_message(bob, bobs_chat.id, "user", "Still here?")
    bobs_deck = decks.create(bob, "Sona control", "")

    delete_account(db_connection, alice)

    assert not _auth_user_exists(db_connection, alice)
    assert conversations.list_for_user(alice) == []
    assert decks.get(alice, deck.id) is None
    in_chat = messages_table.c.conversation_id == chat.id
    count = select(func.count()).select_from(messages_table).where(in_chat)
    assert db_connection.execute(count).scalar_one() == 0
    assert _auth_user_exists(db_connection, bob)
    assert conversations.history(bob, bobs_chat.id) == [("user", "Still here?")]
    assert decks.get(bob, bobs_deck.id) == bobs_deck


def test_deleting_an_account_that_is_already_gone_is_not_an_error(
    db_connection: Connection, new_auth_user: Callable[[], uuid.UUID]
) -> None:
    alice = new_auth_user()
    delete_account(db_connection, alice)

    delete_account(db_connection, alice)

    assert not _auth_user_exists(db_connection, alice)
