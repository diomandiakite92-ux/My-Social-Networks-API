"""Shared database lookups and domain authorization checks."""

from __future__ import annotations

import sqlite3

from fastapi import HTTPException, status

from .database import row_dict, rows_dict


def one(connection: sqlite3.Connection, query: str, params: tuple = ()) -> dict:
    result = row_dict(connection.execute(query, params).fetchone())
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ressource introuvable.")
    return result


def many(connection: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    return rows_dict(connection.execute(query, params).fetchall())


def require_user(connection: sqlite3.Connection, user_id: int) -> dict:
    return one(connection, "SELECT * FROM users WHERE id = ?", (user_id,))


def require_event(connection: sqlite3.Connection, event_id: int) -> dict:
    return one(connection, "SELECT * FROM events WHERE id = ?", (event_id,))


def require_group(connection: sqlite3.Connection, group_id: int) -> dict:
    return one(connection, "SELECT * FROM groups WHERE id = ?", (group_id,))


def is_event_organizer(connection: sqlite3.Connection, event_id: int, user_id: int) -> bool:
    return connection.execute(
        "SELECT 1 FROM event_organizers WHERE event_id = ? AND user_id = ?",
        (event_id, user_id),
    ).fetchone() is not None


def is_event_participant(connection: sqlite3.Connection, event_id: int, user_id: int) -> bool:
    return connection.execute(
        "SELECT 1 FROM event_participants WHERE event_id = ? AND user_id = ?",
        (event_id, user_id),
    ).fetchone() is not None


def is_event_member(connection: sqlite3.Connection, event_id: int, user_id: int) -> bool:
    return is_event_organizer(connection, event_id, user_id) or is_event_participant(
        connection, event_id, user_id
    )


def require_event_member(connection: sqlite3.Connection, event_id: int, user_id: int) -> dict:
    event = require_event(connection, event_id)
    if not is_event_member(connection, event_id, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès réservé aux membres de l’événement.")
    return event


def require_event_participant(connection: sqlite3.Connection, event_id: int, user_id: int) -> dict:
    event = require_event(connection, event_id)
    if not is_event_participant(connection, event_id, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Action réservée aux participants de l’événement.")
    return event


def require_event_organizer(connection: sqlite3.Connection, event_id: int, user_id: int) -> dict:
    event = require_event(connection, event_id)
    if not is_event_organizer(connection, event_id, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Action réservée aux organisateurs.")
    return event


def require_event_visible(
    connection: sqlite3.Connection, event_id: int, viewer_id: int | None
) -> dict:
    event = require_event(connection, event_id)
    if event["visibility"] == "private" and (
        viewer_id is None or not is_event_member(connection, event_id, viewer_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement introuvable.")
    return event


def group_role(connection: sqlite3.Connection, group_id: int, user_id: int) -> str | None:
    record = connection.execute(
        "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?",
        (group_id, user_id),
    ).fetchone()
    return record["role"] if record is not None else None


def require_group_member(connection: sqlite3.Connection, group_id: int, user_id: int) -> dict:
    group = require_group(connection, group_id)
    if group_role(connection, group_id, user_id) is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Action réservée aux membres du groupe.")
    return group


def require_group_admin(connection: sqlite3.Connection, group_id: int, user_id: int) -> dict:
    group = require_group(connection, group_id)
    if group_role(connection, group_id, user_id) != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Action réservée aux administrateurs du groupe.")
    return group


def require_group_visible(
    connection: sqlite3.Connection, group_id: int, viewer_id: int | None
) -> dict:
    group = require_group(connection, group_id)
    if group["visibility"] != "public" and (
        viewer_id is None or group_role(connection, group_id, viewer_id) is None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Groupe introuvable.")
    return group


def event_payload(connection: sqlite3.Connection, event: dict) -> dict:
    result = dict(event)
    result["shopping_list_enabled"] = bool(result["shopping_list_enabled"])
    result["carpool_enabled"] = bool(result["carpool_enabled"])
    result["organizer_ids"] = [
        row["user_id"]
        for row in connection.execute(
            "SELECT user_id FROM event_organizers WHERE event_id = ? ORDER BY user_id",
            (event["id"],),
        ).fetchall()
    ]
    result["participant_ids"] = [
        row["user_id"]
        for row in connection.execute(
            "SELECT user_id FROM event_participants WHERE event_id = ? ORDER BY user_id",
            (event["id"],),
        ).fetchall()
    ]
    return result


def group_payload(connection: sqlite3.Connection, group: dict) -> dict:
    result = dict(group)
    result["allow_member_posts"] = bool(result["allow_member_posts"])
    result["allow_member_events"] = bool(result["allow_member_events"])
    result["member_ids"] = [
        row["user_id"]
        for row in connection.execute(
            "SELECT user_id FROM group_members WHERE group_id = ? ORDER BY user_id",
            (group["id"],),
        ).fetchall()
    ]
    result["admin_ids"] = [
        row["user_id"]
        for row in connection.execute(
            "SELECT user_id FROM group_members WHERE group_id = ? AND role = 'admin' ORDER BY user_id",
            (group["id"],),
        ).fetchall()
    ]
    return result


def require_thread(connection: sqlite3.Connection, thread_id: int) -> dict:
    return one(connection, "SELECT * FROM discussion_threads WHERE id = ?", (thread_id,))


def require_thread_member(
    connection: sqlite3.Connection, thread: dict, user_id: int
) -> None:
    if thread["event_id"] is not None:
        require_event_member(connection, thread["event_id"], user_id)
    elif thread["group_id"] is not None:
        require_group_member(connection, thread["group_id"], user_id)


def require_message(connection: sqlite3.Connection, message_id: int) -> dict:
    return one(connection, "SELECT * FROM messages WHERE id = ?", (message_id,))


def require_album(connection: sqlite3.Connection, album_id: int) -> dict:
    return one(connection, "SELECT * FROM albums WHERE id = ?", (album_id,))


def require_photo(connection: sqlite3.Connection, photo_id: int) -> dict:
    return one(connection, "SELECT * FROM photos WHERE id = ?", (photo_id,))


def require_poll(connection: sqlite3.Connection, poll_id: int) -> dict:
    return one(connection, "SELECT * FROM polls WHERE id = ?", (poll_id,))


def require_ticket_type(connection: sqlite3.Connection, ticket_type_id: int) -> dict:
    return one(connection, "SELECT * FROM ticket_types WHERE id = ?", (ticket_type_id,))


def require_shopping_item(connection: sqlite3.Connection, item_id: int) -> dict:
    return one(connection, "SELECT * FROM shopping_items WHERE id = ?", (item_id,))


def require_ride(connection: sqlite3.Connection, ride_id: int) -> dict:
    return one(connection, "SELECT * FROM rides WHERE id = ?", (ride_id,))
