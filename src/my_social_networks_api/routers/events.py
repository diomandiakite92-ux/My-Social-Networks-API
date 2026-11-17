from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from ..common import (
    event_payload,
    is_event_organizer,
    many,
    one,
    require_event_organizer,
    require_event_visible,
    require_group,
    require_group_member,
    require_user,
)
from ..database import db_connection, datetime_to_storage, utc_now
from ..schemas import EventCreate, EventUpdate


router = APIRouter(prefix="/events", tags=["Événements"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate) -> dict:
    with db_connection(write=True) as connection:
        creator_id = payload.creator_id
        require_user(connection, creator_id)
        organizer_ids = set(payload.organizer_ids)
        organizer_ids.add(creator_id)
        for user_id in organizer_ids | set(payload.participant_ids):
            require_user(connection, user_id)

        participant_ids = set(payload.participant_ids)
        if payload.group_id is not None:
            group = require_group(connection, payload.group_id)
            require_group_member(connection, payload.group_id, creator_id)
            creator_role = connection.execute(
                "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?",
                (payload.group_id, creator_id),
            ).fetchone()["role"]
            if creator_role != "admin" and not group["allow_member_events"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Les membres ne sont pas autorisés à créer des événements dans ce groupe.",
                )
            participant_ids.update(
                row["user_id"]
                for row in connection.execute(
                    "SELECT user_id FROM group_members WHERE group_id = ?",
                    (payload.group_id,),
                ).fetchall()
            )

        cursor = connection.execute(
            "INSERT INTO events (name, description, starts_at, ends_at, location, cover_image_url, "
            "visibility, group_id, shopping_list_enabled, carpool_enabled, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payload.name,
                payload.description,
                datetime_to_storage(payload.starts_at),
                datetime_to_storage(payload.ends_at),
                payload.location,
                payload.cover_image_url,
                payload.visibility,
                payload.group_id,
                int(payload.shopping_list_enabled),
                int(payload.carpool_enabled),
                creator_id,
                utc_now(),
            ),
        )
        event_id = cursor.lastrowid
        connection.executemany(
            "INSERT INTO event_organizers (event_id, user_id) VALUES (?, ?)",
            [(event_id, user_id) for user_id in sorted(organizer_ids)],
        )
        connection.executemany(
            "INSERT OR IGNORE INTO event_participants (event_id, user_id) VALUES (?, ?)",
            [(event_id, user_id) for user_id in sorted(participant_ids)],
        )
        connection.execute(
            "INSERT INTO discussion_threads (event_id, created_at) VALUES (?, ?)",
            (event_id, utc_now()),
        )
        event = one(connection, "SELECT * FROM events WHERE id = ?", (event_id,))
        return event_payload(connection, event)


@router.get("")
def list_events(
    search: str | None = Query(default=None, min_length=1),
    viewer_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    with db_connection() as connection:
        params: list = []
        where = "visibility = 'public'"
        if viewer_id is not None:
            require_user(connection, viewer_id)
            where = (
                "(visibility = 'public' OR EXISTS (SELECT 1 FROM event_participants ep "
                "WHERE ep.event_id = events.id AND ep.user_id = ?) OR EXISTS "
                "(SELECT 1 FROM event_organizers eo WHERE eo.event_id = events.id AND eo.user_id = ?))"
            )
            params.extend((viewer_id, viewer_id))
        if search:
            where += " AND (name LIKE ? OR description LIKE ? OR location LIKE ?)"
            term = f"%{search.strip()}%"
            params.extend((term, term, term))
        params.extend((limit, offset))
        records = many(
            connection,
            f"SELECT * FROM events WHERE {where} ORDER BY starts_at LIMIT ? OFFSET ?",
            tuple(params),
        )
        return [event_payload(connection, event) for event in records]


@router.get("/{event_id}")
def get_event(event_id: int, viewer_id: int | None = Query(default=None, gt=0)) -> dict:
    with db_connection() as connection:
        event = require_event_visible(connection, event_id, viewer_id)
        return event_payload(connection, event)


@router.patch("/{event_id}")
def update_event(
    event_id: int,
    payload: EventUpdate,
    actor_id: int = Query(gt=0),
) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Indiquez au moins un champ à modifier.")
    with db_connection(write=True) as connection:
        current = require_event_organizer(connection, event_id, actor_id)
        allowed_null = {"cover_image_url"}
        if any(value is None and key not in allowed_null for key, value in changes.items()):
            raise HTTPException(status_code=422, detail="Un champ obligatoire ne peut pas être nul.")
        starts_at = changes.get("starts_at", datetime.fromisoformat(current["starts_at"]))
        ends_at = changes.get("ends_at", datetime.fromisoformat(current["ends_at"]))
        if starts_at is not None and ends_at is not None and ends_at <= starts_at:
            raise HTTPException(status_code=422, detail="La date de fin doit être postérieure à la date de début.")
        if "starts_at" in changes and changes["starts_at"] is not None:
            changes["starts_at"] = datetime_to_storage(changes["starts_at"])
        if "ends_at" in changes and changes["ends_at"] is not None:
            changes["ends_at"] = datetime_to_storage(changes["ends_at"])
        for key in ("shopping_list_enabled", "carpool_enabled"):
            if key in changes and changes[key] is not None:
                changes[key] = int(changes[key])
        columns = ", ".join(f"{key} = ?" for key in changes)
        connection.execute(
            f"UPDATE events SET {columns} WHERE id = ?",
            (*changes.values(), event_id),
        )
        return event_payload(connection, one(connection, "SELECT * FROM events WHERE id = ?", (event_id,)))


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        require_event_organizer(connection, event_id, actor_id)
        connection.execute("DELETE FROM events WHERE id = ?", (event_id,))


@router.get("/{event_id}/participants")
def list_participants(
    event_id: int,
    viewer_id: int | None = Query(default=None, gt=0),
) -> list[dict]:
    with db_connection() as connection:
        require_event_visible(connection, event_id, viewer_id)
        return many(
            connection,
            "SELECT u.* FROM users u JOIN event_participants ep ON ep.user_id = u.id "
            "WHERE ep.event_id = ? ORDER BY u.id",
            (event_id,),
        )


@router.get("/{event_id}/organizers")
def list_organizers(
    event_id: int,
    viewer_id: int | None = Query(default=None, gt=0),
) -> list[dict]:
    with db_connection() as connection:
        require_event_visible(connection, event_id, viewer_id)
        return many(
            connection,
            "SELECT u.* FROM users u JOIN event_organizers eo ON eo.user_id = u.id "
            "WHERE eo.event_id = ? ORDER BY u.id",
            (event_id,),
        )


@router.post("/{event_id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_participant(event_id: int, user_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        require_event_organizer(connection, event_id, actor_id)
        require_user(connection, user_id)
        connection.execute(
            "INSERT OR IGNORE INTO event_participants (event_id, user_id) VALUES (?, ?)",
            (event_id, user_id),
        )


@router.delete("/{event_id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_participant(event_id: int, user_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        require_event_organizer(connection, event_id, actor_id)
        connection.execute(
            "DELETE FROM event_participants WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        )


@router.post("/{event_id}/organizers/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_organizer(event_id: int, user_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        require_event_organizer(connection, event_id, actor_id)
        require_user(connection, user_id)
        connection.execute(
            "INSERT OR IGNORE INTO event_organizers (event_id, user_id) VALUES (?, ?)",
            (event_id, user_id),
        )


@router.delete("/{event_id}/organizers/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_organizer(event_id: int, user_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        require_event_organizer(connection, event_id, actor_id)
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM event_organizers WHERE event_id = ?",
            (event_id,),
        ).fetchone()["count"]
        exists = is_event_organizer(connection, event_id, user_id)
        if exists and count <= 1:
            raise HTTPException(status_code=409, detail="Un événement doit conserver au moins un organisateur.")
        connection.execute(
            "DELETE FROM event_organizers WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        )
