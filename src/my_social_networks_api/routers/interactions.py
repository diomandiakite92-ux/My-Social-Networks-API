from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query, status

from ..common import (
    many,
    one,
    require_album,
    require_event_member,
    require_event_organizer,
    require_event_participant,
    require_event_visible,
    require_group_visible,
    require_message,
    require_photo,
    require_thread,
    require_thread_member,
    require_user,
)
from ..database import db_connection, utc_now
from ..schemas import AlbumCreate, AlbumUpdate, PhotoCreate, PhotoUpdate, TextCreate, TextUpdate


router = APIRouter(tags=["Discussions et albums photo"])


def _thread_context(connection: sqlite3.Connection, thread_id: int, user_id: int) -> dict:
    thread = require_thread(connection, thread_id)
    require_thread_member(connection, thread, user_id)
    return thread


def _can_manage_thread_content(
    connection: sqlite3.Connection, thread: dict, content_author_id: int, actor_id: int
) -> bool:
    if actor_id == content_author_id:
        return True
    if thread["event_id"] is not None:
        return connection.execute(
            "SELECT 1 FROM event_organizers WHERE event_id = ? AND user_id = ?",
            (thread["event_id"], actor_id),
        ).fetchone() is not None
    if thread["group_id"] is not None:
        return connection.execute(
            "SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ? AND role = 'admin'",
            (thread["group_id"], actor_id),
        ).fetchone() is not None
    return False


def _ensure_group_post_allowed(connection: sqlite3.Connection, thread: dict, author_id: int) -> None:
    if thread["group_id"] is None:
        return
    group = connection.execute(
        "SELECT allow_member_posts FROM groups WHERE id = ?", (thread["group_id"],)
    ).fetchone()
    role = connection.execute(
        "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?",
        (thread["group_id"], author_id),
    ).fetchone()["role"]
    if role != "admin" and not group["allow_member_posts"]:
        raise HTTPException(status_code=403, detail="Les membres ne sont pas autorisés à publier dans ce groupe.")


def _album_context(connection: sqlite3.Connection, album_id: int, user_id: int | None) -> tuple[dict, int]:
    album = require_album(connection, album_id)
    if user_id is None:
        require_event_visible(connection, album["event_id"], None)
    else:
        require_event_visible(connection, album["event_id"], user_id)
    return album, album["event_id"]


def _photo_context(connection: sqlite3.Connection, photo_id: int, user_id: int | None) -> tuple[dict, dict, int]:
    photo = require_photo(connection, photo_id)
    album = require_album(connection, photo["album_id"])
    if user_id is None:
        require_event_visible(connection, album["event_id"], None)
    else:
        require_event_visible(connection, album["event_id"], user_id)
    return photo, album, album["event_id"]


@router.get("/events/{event_id}/discussion")
def get_event_discussion(event_id: int, viewer_id: int | None = Query(default=None, gt=0)) -> dict:
    with db_connection() as connection:
        require_event_visible(connection, event_id, viewer_id)
        return one(connection, "SELECT * FROM discussion_threads WHERE event_id = ?", (event_id,))


@router.get("/groups/{group_id}/discussion")
def get_group_discussion(group_id: int, viewer_id: int | None = Query(default=None, gt=0)) -> dict:
    with db_connection() as connection:
        require_group_visible(connection, group_id, viewer_id)
        return one(connection, "SELECT * FROM discussion_threads WHERE group_id = ?", (group_id,))


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, viewer_id: int = Query(gt=0)) -> dict:
    with db_connection() as connection:
        thread = _thread_context(connection, thread_id, viewer_id)
        return thread


@router.get("/threads/{thread_id}/messages")
def list_messages(
    thread_id: int,
    viewer_id: int = Query(gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    with db_connection() as connection:
        _thread_context(connection, thread_id, viewer_id)
        return many(
            connection,
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at, id LIMIT ? OFFSET ?",
            (thread_id, limit, offset),
        )


@router.post("/threads/{thread_id}/messages", status_code=status.HTTP_201_CREATED)
def create_message(thread_id: int, payload: TextCreate) -> dict:
    with db_connection(write=True) as connection:
        thread = _thread_context(connection, thread_id, payload.author_id)
        _ensure_group_post_allowed(connection, thread, payload.author_id)
        cursor = connection.execute(
            "INSERT INTO messages (thread_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
            (thread_id, payload.author_id, payload.body, utc_now()),
        )
        return one(connection, "SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,))


@router.patch("/messages/{message_id}")
def update_message(message_id: int, payload: TextUpdate, actor_id: int = Query(gt=0)) -> dict:
    with db_connection(write=True) as connection:
        message = require_message(connection, message_id)
        thread = _thread_context(connection, message["thread_id"], actor_id)
        if not _can_manage_thread_content(connection, thread, message["author_id"], actor_id):
            raise HTTPException(status_code=403, detail="Seul l’auteur ou un gestionnaire peut modifier ce message.")
        connection.execute("UPDATE messages SET body = ? WHERE id = ?", (payload.body, message_id))
        return one(connection, "SELECT * FROM messages WHERE id = ?", (message_id,))


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(message_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        message = require_message(connection, message_id)
        thread = _thread_context(connection, message["thread_id"], actor_id)
        if not _can_manage_thread_content(connection, thread, message["author_id"], actor_id):
            raise HTTPException(status_code=403, detail="Seul l’auteur ou un gestionnaire peut supprimer ce message.")
        connection.execute("DELETE FROM messages WHERE id = ?", (message_id,))


@router.get("/messages/{message_id}/comments")
def list_message_comments(
    message_id: int,
    viewer_id: int = Query(gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    with db_connection() as connection:
        message = require_message(connection, message_id)
        _thread_context(connection, message["thread_id"], viewer_id)
        return many(
            connection,
            "SELECT * FROM message_comments WHERE message_id = ? ORDER BY created_at, id LIMIT ? OFFSET ?",
            (message_id, limit, offset),
        )


@router.post("/messages/{message_id}/comments", status_code=status.HTTP_201_CREATED)
def create_message_comment(message_id: int, payload: TextCreate) -> dict:
    with db_connection(write=True) as connection:
        message = require_message(connection, message_id)
        thread = _thread_context(connection, message["thread_id"], payload.author_id)
        _ensure_group_post_allowed(connection, thread, payload.author_id)
        cursor = connection.execute(
            "INSERT INTO message_comments (message_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
            (message_id, payload.author_id, payload.body, utc_now()),
        )
        return one(connection, "SELECT * FROM message_comments WHERE id = ?", (cursor.lastrowid,))


@router.delete("/message-comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message_comment(comment_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        comment = one(connection, "SELECT * FROM message_comments WHERE id = ?", (comment_id,))
        message = require_message(connection, comment["message_id"])
        thread = _thread_context(connection, message["thread_id"], actor_id)
        if not _can_manage_thread_content(connection, thread, comment["author_id"], actor_id):
            raise HTTPException(status_code=403, detail="Seul l’auteur ou un gestionnaire peut supprimer ce commentaire.")
        connection.execute("DELETE FROM message_comments WHERE id = ?", (comment_id,))


@router.post("/events/{event_id}/albums", status_code=status.HTTP_201_CREATED)
def create_album(event_id: int, payload: AlbumCreate) -> dict:
    with db_connection(write=True) as connection:
        require_event_member(connection, event_id, payload.creator_id)
        cursor = connection.execute(
            "INSERT INTO albums (event_id, name, created_by, created_at) VALUES (?, ?, ?, ?)",
            (event_id, payload.name.strip(), payload.creator_id, utc_now()),
        )
        return one(connection, "SELECT * FROM albums WHERE id = ?", (cursor.lastrowid,))


@router.get("/events/{event_id}/albums")
def list_albums(
    event_id: int,
    viewer_id: int | None = Query(default=None, gt=0),
) -> list[dict]:
    with db_connection() as connection:
        require_event_visible(connection, event_id, viewer_id)
        return many(connection, "SELECT * FROM albums WHERE event_id = ? ORDER BY id", (event_id,))


@router.get("/albums/{album_id}")
def get_album(album_id: int, viewer_id: int | None = Query(default=None, gt=0)) -> dict:
    with db_connection() as connection:
        album, _ = _album_context(connection, album_id, viewer_id)
        return album


@router.patch("/albums/{album_id}")
def update_album(album_id: int, payload: AlbumUpdate, actor_id: int = Query(gt=0)) -> dict:
    if payload.name is None or not payload.name.strip():
        raise HTTPException(status_code=422, detail="Le nom de l’album est obligatoire.")
    with db_connection(write=True) as connection:
        album = require_album(connection, album_id)
        require_event_member(connection, album["event_id"], actor_id)
        if actor_id != album["created_by"]:
            require_event_organizer(connection, album["event_id"], actor_id)
        connection.execute("UPDATE albums SET name = ? WHERE id = ?", (payload.name.strip(), album_id))
        return one(connection, "SELECT * FROM albums WHERE id = ?", (album_id,))


@router.delete("/albums/{album_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_album(album_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        album = require_album(connection, album_id)
        require_event_member(connection, album["event_id"], actor_id)
        if actor_id != album["created_by"]:
            require_event_organizer(connection, album["event_id"], actor_id)
        connection.execute("DELETE FROM albums WHERE id = ?", (album_id,))


@router.post("/albums/{album_id}/photos", status_code=status.HTTP_201_CREATED)
def create_photo(album_id: int, payload: PhotoCreate) -> dict:
    with db_connection(write=True) as connection:
        album = require_album(connection, album_id)
        require_event_participant(connection, album["event_id"], payload.participant_id)
        cursor = connection.execute(
            "INSERT INTO photos (album_id, participant_id, image_url, caption, created_at) VALUES (?, ?, ?, ?, ?)",
            (album_id, payload.participant_id, payload.image_url, payload.caption, utc_now()),
        )
        return one(connection, "SELECT * FROM photos WHERE id = ?", (cursor.lastrowid,))


@router.get("/albums/{album_id}/photos")
def list_photos(
    album_id: int,
    viewer_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    with db_connection() as connection:
        _album_context(connection, album_id, viewer_id)
        return many(
            connection,
            "SELECT * FROM photos WHERE album_id = ? ORDER BY created_at, id LIMIT ? OFFSET ?",
            (album_id, limit, offset),
        )


@router.patch("/photos/{photo_id}")
def update_photo(photo_id: int, payload: PhotoUpdate, actor_id: int = Query(gt=0)) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Indiquez des champs non nuls à modifier.")
    with db_connection(write=True) as connection:
        photo, album, event_id = _photo_context(connection, photo_id, actor_id)
        require_event_member(connection, event_id, actor_id)
        if actor_id != photo["participant_id"]:
            require_event_organizer(connection, event_id, actor_id)
        columns = ", ".join(f"{key} = ?" for key in changes)
        connection.execute(f"UPDATE photos SET {columns} WHERE id = ?", (*changes.values(), photo_id))
        return one(connection, "SELECT * FROM photos WHERE id = ?", (photo_id,))


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(photo_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        photo, _, event_id = _photo_context(connection, photo_id, actor_id)
        require_event_member(connection, event_id, actor_id)
        if actor_id != photo["participant_id"]:
            require_event_organizer(connection, event_id, actor_id)
        connection.execute("DELETE FROM photos WHERE id = ?", (photo_id,))


@router.get("/photos/{photo_id}/comments")
def list_photo_comments(
    photo_id: int,
    viewer_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    with db_connection() as connection:
        _photo_context(connection, photo_id, viewer_id)
        return many(
            connection,
            "SELECT * FROM photo_comments WHERE photo_id = ? ORDER BY created_at, id LIMIT ? OFFSET ?",
            (photo_id, limit, offset),
        )


@router.post("/photos/{photo_id}/comments", status_code=status.HTTP_201_CREATED)
def create_photo_comment(photo_id: int, payload: TextCreate) -> dict:
    with db_connection(write=True) as connection:
        _, _, event_id = _photo_context(connection, photo_id, payload.author_id)
        require_event_participant(connection, event_id, payload.author_id)
        cursor = connection.execute(
            "INSERT INTO photo_comments (photo_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
            (photo_id, payload.author_id, payload.body, utc_now()),
        )
        return one(connection, "SELECT * FROM photo_comments WHERE id = ?", (cursor.lastrowid,))


@router.delete("/photo-comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo_comment(comment_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        comment = one(connection, "SELECT * FROM photo_comments WHERE id = ?", (comment_id,))
        photo, _, event_id = _photo_context(connection, comment["photo_id"], actor_id)
        require_event_member(connection, event_id, actor_id)
        if actor_id != comment["author_id"]:
            require_event_organizer(connection, event_id, actor_id)
        connection.execute("DELETE FROM photo_comments WHERE id = ?", (comment_id,))


@router.patch("/photo-comments/{comment_id}")
def update_photo_comment(comment_id: int, payload: TextUpdate, actor_id: int = Query(gt=0)) -> dict:
    with db_connection(write=True) as connection:
        comment = one(connection, "SELECT * FROM photo_comments WHERE id = ?", (comment_id,))
        photo, _, event_id = _photo_context(connection, comment["photo_id"], actor_id)
        require_event_member(connection, event_id, actor_id)
        if actor_id != comment["author_id"]:
            require_event_organizer(connection, event_id, actor_id)
        connection.execute("UPDATE photo_comments SET body = ? WHERE id = ?", (payload.body, comment_id))
        return one(connection, "SELECT * FROM photo_comments WHERE id = ?", (comment_id,))


@router.patch("/message-comments/{comment_id}")
def update_message_comment(comment_id: int, payload: TextUpdate, actor_id: int = Query(gt=0)) -> dict:
    with db_connection(write=True) as connection:
        comment = one(connection, "SELECT * FROM message_comments WHERE id = ?", (comment_id,))
        message = require_message(connection, comment["message_id"])
        thread = _thread_context(connection, message["thread_id"], actor_id)
        if not _can_manage_thread_content(connection, thread, comment["author_id"], actor_id):
            raise HTTPException(status_code=403, detail="Seul l’auteur ou un gestionnaire peut modifier ce commentaire.")
        connection.execute("UPDATE message_comments SET body = ? WHERE id = ?", (payload.body, comment_id))
        return one(connection, "SELECT * FROM message_comments WHERE id = ?", (comment_id,))
