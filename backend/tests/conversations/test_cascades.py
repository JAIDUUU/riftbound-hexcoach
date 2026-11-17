"""Database-level cascades (migration 0006): only Postgres can prove these."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import ColumnElement, Connection, Table, func, select, text

from backend.conversations.limits import Limits
from backend.conversations.schema import conversations_table, messages_table
from backend.conversations.store import SqlConversationStore

pytestmark = pytest.mark.integration


def _count(connection: Connection, table: Table, where: ColumnElement[bool]) -> int:
    return connection.execute(select(func.count()).select_from(table).where(where)).scalar_one()


def test_deleting_a_conversation_deletes_its_message_rows(
    db_connection: Connection, new_auth_user: Callable[[], uuid.UUID]
) -> None:
    store = SqlConversationStore(db_connection, Limits())
    alice = new_auth_user()
    conversation = store.create(alice, None)
    store.add_message(alice, conversation.id, "user", "one")
    store.add_message(alice, conversation.id, "assistant", "two")

    store.delete(alice, conversation.id)

    in_conversation = messages_table.c.conversation_id == conversation.id
    assert _count(db_connection, messages_table, in_conversation) == 0


def test_deleting_the_account_deletes_its_conversations(
    db_connection: Connection, new_auth_user: Callable[[], uuid.UUID]
) -> None:
    store = SqlConversationStore(db_connection, Limits())
    alice = new_auth_user()
    conversation = store.create(alice, None)
    store.add_message(alice, conversation.id, "user", "one")

    db_connection.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": alice})

    owned_by_alice = conversations_table.c.user_id == alice
    in_conversation = messages_table.c.conversation_id == conversation.id
    assert _count(db_connection, conversations_table, owned_by_alice) == 0
    assert _count(db_connection, messages_table, in_conversation) == 0
