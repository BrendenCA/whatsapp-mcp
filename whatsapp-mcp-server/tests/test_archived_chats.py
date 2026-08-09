"""Tests for hiding WhatsApp-archived chats in list_chats / list_messages.

Archive state lives in whatsmeow's store (whatsapp.db) as
whatsmeow_chat_settings.archived, and whatsmeow records DM chats under their LID
while messages.db records them under the phone JID, so the fixtures below mirror
both stores and the whatsmeow_lid_map that joins them.
"""

import sqlite3

import pytest

import whatsapp

# Chats in the fixture databases.
ACTIVE_DM = "111111111@s.whatsapp.net"
ARCHIVED_DM = "222222222@s.whatsapp.net"  # archived, stored by whatsmeow as a LID
ARCHIVED_DM_LID = "999888777666@lid"
ACTIVE_GROUP = "group-active@g.us"
ARCHIVED_GROUP = "group-archived@g.us"

ALL_CHATS = {ACTIVE_DM, ARCHIVED_DM, ACTIVE_GROUP, ARCHIVED_GROUP}
ACTIVE_CHATS = {ACTIVE_DM, ACTIVE_GROUP}
ALL_MESSAGES = {"m-active-dm", "m-archived-dm", "m-active-group", "m-archived-group"}
ACTIVE_MESSAGES = {"m-active-dm", "m-active-group"}


def _make_messages_db(path):
    """Create a minimal messages.db matching the real bridge schema."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE chats (
            jid TEXT PRIMARY KEY,
            name TEXT,
            last_message_time TIMESTAMP
        );
        CREATE TABLE messages (
            id TEXT,
            chat_jid TEXT,
            sender TEXT,
            content TEXT,
            timestamp TIMESTAMP,
            is_from_me BOOLEAN,
            media_type TEXT,
            filename TEXT,
            quoted_message_id TEXT,
            PRIMARY KEY (id, chat_jid),
            FOREIGN KEY (chat_jid) REFERENCES chats(jid)
        );
        """
    )
    conn.executemany(
        "INSERT INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)",
        [
            (ACTIVE_DM, "Active Alice", "2024-01-15 10:00:00+00:00"),
            (ARCHIVED_DM, "Archived Bob", "2024-01-15 11:00:00+00:00"),
            (ACTIVE_GROUP, "Active Group", "2024-01-15 12:00:00+00:00"),
            (ARCHIVED_GROUP, "Archived Group", "2024-01-15 13:00:00+00:00"),
        ],
    )
    conn.executemany(
        """INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            ("m-active-dm", ACTIVE_DM, "111111111", "needle from active dm", "2024-01-15 10:00:00+00:00", 0),
            ("m-archived-dm", ARCHIVED_DM, "222222222", "needle from archived dm", "2024-01-15 11:00:00+00:00", 0),
            ("m-active-group", ACTIVE_GROUP, "111111111", "needle from active group", "2024-01-15 12:00:00+00:00", 0),
            (
                "m-archived-group",
                ARCHIVED_GROUP,
                "222222222",
                "needle from archived group",
                "2024-01-15 13:00:00+00:00",
                0,
            ),
        ],
    )
    conn.commit()
    conn.close()


def _make_whatsmeow_db(path):
    """Create the whatsmeow tables this feature reads, with real column shapes."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE whatsmeow_chat_settings (
            our_jid     TEXT,
            chat_jid    TEXT,
            muted_until BIGINT  NOT NULL DEFAULT 0,
            pinned      BOOLEAN NOT NULL DEFAULT false,
            archived    BOOLEAN NOT NULL DEFAULT false,
            PRIMARY KEY (our_jid, chat_jid)
        );
        CREATE TABLE whatsmeow_lid_map (
            lid TEXT PRIMARY KEY,
            pn  TEXT UNIQUE NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO whatsmeow_chat_settings (our_jid, chat_jid, muted_until, pinned, archived) VALUES (?, ?, ?, ?, ?)",
        [
            # Archived DM, recorded by whatsmeow under its LID.
            ("me@s.whatsapp.net", ARCHIVED_DM_LID, 0, 0, 1),
            ("me@s.whatsapp.net", ARCHIVED_GROUP, 0, 0, 1),
            # Muted and pinned but not archived: must stay visible.
            ("me@s.whatsapp.net", ACTIVE_GROUP, 9999999999, 1, 0),
        ],
    )
    conn.execute(
        "INSERT INTO whatsmeow_lid_map (lid, pn) VALUES (?, ?)",
        (ARCHIVED_DM_LID.split("@")[0], ARCHIVED_DM.split("@")[0]),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def databases(tmp_path, monkeypatch):
    messages_path = tmp_path / "messages.db"
    whatsmeow_path = tmp_path / "whatsapp.db"
    _make_messages_db(str(messages_path))
    _make_whatsmeow_db(str(whatsmeow_path))
    monkeypatch.setattr(whatsapp, "MESSAGES_DB_PATH", str(messages_path))
    monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", str(whatsmeow_path))
    return messages_path, whatsmeow_path


def _jids(chats):
    return {chat["jid"] for chat in chats}


def _message_ids(messages):
    return {message["id"] for message in messages}


class TestArchivedChatJids:
    """Tests for the whatsapp.db archive lookup."""

    def test_returns_both_jid_spellings(self, databases):
        assert whatsapp._archived_chat_jids() == {ARCHIVED_DM_LID, ARCHIVED_DM, ARCHIVED_GROUP}

    def test_missing_whatsmeow_db_returns_empty_set(self, databases, monkeypatch):
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", "/nonexistent/whatsapp.db")
        assert whatsapp._archived_chat_jids() == set()

    def test_unreadable_whatsmeow_db_returns_empty_set(self, databases, monkeypatch, tmp_path):
        broken = tmp_path / "broken.db"
        broken.write_text("not a database")
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", str(broken))
        assert whatsapp._archived_chat_jids() == set()


class TestListChatsArchiveFilter:
    def test_default_hides_archived_chats(self, databases):
        """Both spellings resolve: the group matches directly, the DM via the LID map."""
        assert _jids(whatsapp.list_chats(limit=10)) == ACTIVE_CHATS

    def test_include_archived_true_returns_every_chat(self, databases):
        assert _jids(whatsapp.list_chats(limit=10, include_archived=True)) == ALL_CHATS

    def test_include_archived_false_hides_archived_chats(self, databases):
        assert _jids(whatsapp.list_chats(limit=10, include_archived=False)) == ACTIVE_CHATS

    def test_composes_with_query_and_include_last_message(self, databases):
        assert whatsapp.list_chats(query="Archived", include_last_message=False) == []

        chats = whatsapp.list_chats(query="Active")
        assert _jids(chats) == ACTIVE_CHATS
        assert chats[0]["last_message"] is not None

    def test_missing_whatsmeow_db_leaves_results_unfiltered(self, databases, monkeypatch):
        """Without whatsmeow's store there is no archive state, so nothing is dropped."""
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", "/nonexistent/whatsapp.db")
        assert _jids(whatsapp.list_chats(limit=10)) == ALL_CHATS


class TestListMessagesArchiveFilter:
    def test_default_hides_messages_from_archived_chats(self, databases):
        messages = whatsapp.list_messages(query="needle", include_context=False)
        assert _message_ids(messages) == ACTIVE_MESSAGES

    def test_include_archived_true_returns_every_message(self, databases):
        messages = whatsapp.list_messages(query="needle", include_context=False, include_archived=True)
        assert _message_ids(messages) == ALL_MESSAGES

    def test_include_archived_false_hides_archived_messages(self, databases):
        messages = whatsapp.list_messages(query="needle", include_context=False, include_archived=False)
        assert _message_ids(messages) == ACTIVE_MESSAGES

    def test_explicit_chat_jid_still_returns_archived_messages(self, databases):
        """Naming a chat is an explicit request for it, archived or not."""
        messages = whatsapp.list_messages(chat_jid=ARCHIVED_DM, include_context=False)
        assert _message_ids(messages) == {"m-archived-dm"}

    def test_composes_with_sender_and_date_filters(self, databases):
        messages = whatsapp.list_messages(
            after="2024-01-15 09:00:00+00:00",
            before="2024-01-15 23:00:00+00:00",
            sender_phone_number="111111111",
            include_context=False,
        )
        assert _message_ids(messages) == ACTIVE_MESSAGES

    def test_context_expansion_stays_within_visible_chats(self, databases):
        messages = whatsapp.list_messages(query="needle", include_context=True)
        assert _message_ids(messages) == ACTIVE_MESSAGES

    def test_missing_whatsmeow_db_leaves_results_unfiltered(self, databases, monkeypatch):
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", "/nonexistent/whatsapp.db")
        messages = whatsapp.list_messages(query="needle", include_context=False)
        assert _message_ids(messages) == ALL_MESSAGES
