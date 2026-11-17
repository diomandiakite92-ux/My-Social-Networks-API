from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..common import many, one
from ..database import db_connection, row_dict, utc_now
from ..schemas import UserCreate, UserUpdate


router = APIRouter(prefix="/users", tags=["Utilisateurs"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate) -> dict:
    with db_connection(write=True) as connection:
        cursor = connection.execute(
            "INSERT INTO users (first_name, last_name, email, created_at) VALUES (?, ?, ?, ?)",
            (payload.first_name, payload.last_name, payload.email, utc_now()),
        )
        return one(connection, "SELECT * FROM users WHERE id = ?", (cursor.lastrowid,))


@router.get("")
def list_users(
    search: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    with db_connection() as connection:
        if search:
            term = f"%{search.strip()}%"
            return many(
                connection,
                "SELECT * FROM users WHERE first_name LIKE ? OR last_name LIKE ? OR email LIKE ? "
                "ORDER BY id LIMIT ? OFFSET ?",
                (term, term, term, limit, offset),
            )
        return many(connection, "SELECT * FROM users ORDER BY id LIMIT ? OFFSET ?", (limit, offset))


@router.get("/{user_id}")
def get_user(user_id: int) -> dict:
    with db_connection() as connection:
        return one(connection, "SELECT * FROM users WHERE id = ?", (user_id,))


@router.patch("/{user_id}")
def update_user(user_id: int, payload: UserUpdate) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Indiquez au moins un champ à modifier.")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Un champ de profil ne peut pas être nul.")
    with db_connection(write=True) as connection:
        one(connection, "SELECT * FROM users WHERE id = ?", (user_id,))
        columns = ", ".join(f"{key} = ?" for key in changes)
        connection.execute(
            f"UPDATE users SET {columns} WHERE id = ?",
            (*changes.values(), user_id),
        )
        return one(connection, "SELECT * FROM users WHERE id = ?", (user_id,))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int) -> None:
    with db_connection(write=True) as connection:
        one(connection, "SELECT * FROM users WHERE id = ?", (user_id,))
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
