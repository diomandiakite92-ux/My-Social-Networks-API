from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..common import group_payload, group_role, many, one, require_group, require_group_admin, require_group_visible, require_user
from ..database import db_connection, utc_now
from ..schemas import GroupCreate, GroupMemberRoleUpdate, GroupUpdate


router = APIRouter(prefix="/groups", tags=["Groupes"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate) -> dict:
    with db_connection(write=True) as connection:
        require_user(connection, payload.creator_id)
        cursor = connection.execute(
            "INSERT INTO groups (name, description, icon_url, cover_image_url, visibility, "
            "allow_member_posts, allow_member_events, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payload.name,
                payload.description,
                payload.icon_url,
                payload.cover_image_url,
                payload.visibility,
                int(payload.allow_member_posts),
                int(payload.allow_member_events),
                payload.creator_id,
                utc_now(),
            ),
        )
        group_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO group_members (group_id, user_id, role) VALUES (?, ?, 'admin')",
            (group_id, payload.creator_id),
        )
        connection.execute(
            "INSERT INTO discussion_threads (group_id, created_at) VALUES (?, ?)",
            (group_id, utc_now()),
        )
        return group_payload(connection, one(connection, "SELECT * FROM groups WHERE id = ?", (group_id,)))


@router.get("")
def list_groups(
    search: str | None = Query(default=None, min_length=1),
    viewer_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    with db_connection() as connection:
        params: list = []
        if viewer_id is None:
            where = "visibility IN ('public', 'private')"
        else:
            require_user(connection, viewer_id)
            where = (
                "(visibility IN ('public', 'private') OR EXISTS (SELECT 1 FROM group_members gm "
                "WHERE gm.group_id = groups.id AND gm.user_id = ?))"
            )
            params.append(viewer_id)
        if search:
            where += " AND (name LIKE ? OR (visibility = 'public' AND description LIKE ?))"
            term = f"%{search.strip()}%"
            params.extend((term, term))
        params.extend((limit, offset))
        records = many(
            connection,
            f"SELECT * FROM groups WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
            tuple(params),
        )
        result = []
        for group in records:
            is_member = viewer_id is not None and group_role(connection, group["id"], viewer_id) is not None
            if group["visibility"] == "private" and not is_member:
                result.append(
                    {
                        key: group[key]
                        for key in ("id", "name", "visibility", "icon_url", "cover_image_url", "created_at")
                    }
                )
            else:
                result.append(group_payload(connection, group))
        return result


@router.get("/{group_id}")
def get_group(group_id: int, viewer_id: int | None = Query(default=None, gt=0)) -> dict:
    with db_connection() as connection:
        group = require_group_visible(connection, group_id, viewer_id)
        return group_payload(connection, group)


@router.patch("/{group_id}")
def update_group(group_id: int, payload: GroupUpdate, actor_id: int = Query(gt=0)) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Indiquez au moins un champ à modifier.")
    with db_connection(write=True) as connection:
        require_group_admin(connection, group_id, actor_id)
        if any(value is None and key not in {"icon_url", "cover_image_url"} for key, value in changes.items()):
            raise HTTPException(status_code=422, detail="Un champ obligatoire ne peut pas être nul.")
        for key in ("allow_member_posts", "allow_member_events"):
            if key in changes and changes[key] is not None:
                changes[key] = int(changes[key])
        columns = ", ".join(f"{key} = ?" for key in changes)
        connection.execute(f"UPDATE groups SET {columns} WHERE id = ?", (*changes.values(), group_id))
        return group_payload(connection, one(connection, "SELECT * FROM groups WHERE id = ?", (group_id,)))


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        require_group_admin(connection, group_id, actor_id)
        connection.execute("DELETE FROM groups WHERE id = ?", (group_id,))


@router.get("/{group_id}/members")
def list_group_members(group_id: int, viewer_id: int | None = Query(default=None, gt=0)) -> list[dict]:
    with db_connection() as connection:
        require_group_visible(connection, group_id, viewer_id)
        return many(
            connection,
            "SELECT u.*, gm.role FROM users u JOIN group_members gm ON gm.user_id = u.id "
            "WHERE gm.group_id = ? ORDER BY gm.role DESC, u.id",
            (group_id,),
        )


@router.post("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_group_member(
    group_id: int,
    user_id: int,
    actor_id: int = Query(gt=0),
) -> None:
    with db_connection(write=True) as connection:
        group = require_group(connection, group_id)
        if actor_id == user_id and group["visibility"] == "public":
            require_user(connection, actor_id)
        else:
            require_group_admin(connection, group_id, actor_id)
            require_user(connection, user_id)
        connection.execute(
            "INSERT OR IGNORE INTO group_members (group_id, user_id, role) VALUES (?, ?, 'member')",
            (group_id, user_id),
        )


@router.put("/{group_id}/members/{user_id}/role")
def set_group_member_role(
    group_id: int,
    user_id: int,
    payload: GroupMemberRoleUpdate,
    actor_id: int = Query(gt=0),
) -> dict:
    role = payload.role
    with db_connection(write=True) as connection:
        require_group_admin(connection, group_id, actor_id)
        membership = connection.execute(
            "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        ).fetchone()
        if membership is None:
            raise HTTPException(status_code=404, detail="Membre introuvable dans ce groupe.")
        admin_count = connection.execute(
            "SELECT COUNT(*) AS count FROM group_members WHERE group_id = ? AND role = 'admin'",
            (group_id,),
        ).fetchone()["count"]
        if membership["role"] == "admin" and role == "member" and admin_count <= 1:
            raise HTTPException(status_code=409, detail="Un groupe doit conserver au moins un administrateur.")
        connection.execute(
            "UPDATE group_members SET role = ? WHERE group_id = ? AND user_id = ?",
            (role, group_id, user_id),
        )
        return one(
            connection,
            "SELECT u.id, u.first_name, u.last_name, u.email, gm.role "
            "FROM users u JOIN group_members gm ON gm.user_id = u.id "
            "WHERE gm.group_id = ? AND gm.user_id = ?",
            (group_id, user_id),
        )


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_group_member(group_id: int, user_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        membership = connection.execute(
            "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        ).fetchone()
        if membership is None:
            raise HTTPException(status_code=404, detail="Membre introuvable dans ce groupe.")
        if actor_id != user_id:
            require_group_admin(connection, group_id, actor_id)
        if membership["role"] == "admin":
            admin_count = connection.execute(
                "SELECT COUNT(*) AS count FROM group_members WHERE group_id = ? AND role = 'admin'",
                (group_id,),
            ).fetchone()["count"]
            if admin_count <= 1:
                raise HTTPException(status_code=409, detail="Le dernier administrateur ne peut pas quitter le groupe.")
        connection.execute(
            "DELETE FROM group_members WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        )
