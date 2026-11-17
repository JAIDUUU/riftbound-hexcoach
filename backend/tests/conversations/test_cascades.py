"""Database-level cascades (migration 0006): only Postgres can prove these."""

import pytest
from sqlalchemy import ColumnElement, Connection, Table, func, select, text
from tests.conversations.test_store_contract import insert_auth_user

from backend.conversations.limits import Limits
from backend.conversations.schema import conversations_table, messages_table
from backend.conversations.store import SqlConversationStore

pytestmark = pytest.mark.integration


def _count(connection: Connection, table: Table, where: ColumnElement[bool]) -> int:
    return connection.execute(select(func.count()).select_from(table).where(where)).scalar_one()


def test_deleting_a_conversation_deletes_its_message_rows(db_connection: Connection) -> None:
    store = SqlConversationStore(db_connection, Limits())
    alice = insert_auth_user(db_connection)
    conversation = store.create(alice, None)
    store.add_message(alice, conversation.id, "user", "one")
    store.add_message(alice, conversation.id, "assistant", "two")

    store.delete(alice, conversation.id)

    in_conversation = messages_table.c.conversation_id == conversation.id
    assert _count(db_connection, messages_table, in_conversation) == 0


def test_deleting_the_account_deletes_its_conversations(db_connection: Connection) -> None:
    store = SqlConversationStore(db_connection, Limits())
    alice = insert_auth_user(db_connection)
    conversation = store.create(alice, None)
    store.add_message(alice, conversation.id, "user", "one")

    db_connection.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": alice})

    assert _count(db_connection, conversations_table, conversations_table.c.user_id == alice) == 0
    assert (
        _count(db_connection, messages_table, messages_table.c.conversation_id == conversation.id)
        == 0
    )
