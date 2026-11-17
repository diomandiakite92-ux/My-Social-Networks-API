from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from ..common import many, one, require_event_member, require_event_organizer, require_ride, require_shopping_item, require_user
from ..database import db_connection, datetime_to_storage, utc_now
from ..schemas import RideCreate, RideUpdate, ShoppingItemCreate, ShoppingItemUpdate


router = APIRouter(tags=["Liste d’achats et covoiturage"])


def _enabled_event(connection, event_id: int, feature: str, user_id: int) -> dict:
    if feature not in {"shopping_list_enabled", "carpool_enabled"}:
        raise ValueError("Unsupported event feature")
    event = require_event_member(connection, event_id, user_id)
    if not event[feature]:
        label = "La liste d’achats" if feature == "shopping_list_enabled" else "Le covoiturage"
        raise HTTPException(status_code=409, detail=f"{label} n’est pas activé pour cet événement.")
    return event


@router.post("/events/{event_id}/shopping-items", status_code=status.HTTP_201_CREATED)
def create_shopping_item(event_id: int, payload: ShoppingItemCreate) -> dict:
    with db_connection(write=True) as connection:
        _enabled_event(connection, event_id, "shopping_list_enabled", payload.user_id)
        cursor = connection.execute(
            "INSERT INTO shopping_items (event_id, user_id, name, quantity, arrival_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event_id,
                payload.user_id,
                payload.name.strip(),
                payload.quantity,
                datetime_to_storage(payload.arrival_at),
                utc_now(),
            ),
        )
        return one(connection, "SELECT * FROM shopping_items WHERE id = ?", (cursor.lastrowid,))


@router.get("/events/{event_id}/shopping-items")
def list_shopping_items(event_id: int, viewer_id: int = Query(gt=0)) -> list[dict]:
    with db_connection() as connection:
        _enabled_event(connection, event_id, "shopping_list_enabled", viewer_id)
        return many(connection, "SELECT * FROM shopping_items WHERE event_id = ? ORDER BY name COLLATE NOCASE", (event_id,))


@router.patch("/shopping-items/{item_id}")
def update_shopping_item(
    item_id: int,
    payload: ShoppingItemUpdate,
) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("user_id", None)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Indiquez des champs non nuls à modifier.")
    with db_connection(write=True) as connection:
        item = require_shopping_item(connection, item_id)
        _enabled_event(connection, item["event_id"], "shopping_list_enabled", payload.user_id)
        if payload.user_id != item["user_id"]:
            require_event_organizer(connection, item["event_id"], payload.user_id)
        if "name" in changes:
            changes["name"] = changes["name"].strip()
        if "arrival_at" in changes:
            changes["arrival_at"] = datetime_to_storage(changes["arrival_at"])
        columns = ", ".join(f"{key} = ?" for key in changes)
        connection.execute(f"UPDATE shopping_items SET {columns} WHERE id = ?", (*changes.values(), item_id))
        return one(connection, "SELECT * FROM shopping_items WHERE id = ?", (item_id,))


@router.delete("/shopping-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shopping_item(item_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        item = require_shopping_item(connection, item_id)
        _enabled_event(connection, item["event_id"], "shopping_list_enabled", actor_id)
        if actor_id != item["user_id"]:
            require_event_organizer(connection, item["event_id"], actor_id)
        connection.execute("DELETE FROM shopping_items WHERE id = ?", (item_id,))


@router.post("/events/{event_id}/rides", status_code=status.HTTP_201_CREATED)
def create_ride(event_id: int, payload: RideCreate) -> dict:
    with db_connection(write=True) as connection:
        event = _enabled_event(connection, event_id, "carpool_enabled", payload.driver_id)
        if payload.departure_at >= datetime.fromisoformat(event["starts_at"]):
            raise HTTPException(status_code=422, detail="Le départ doit précéder le début de l’événement.")
        require_user(connection, payload.driver_id)
        cursor = connection.execute(
            "INSERT INTO rides (event_id, driver_id, departure_location, departure_at, price_cents, "
            "seats_available, max_time_gap_minutes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                payload.driver_id,
                payload.departure_location.strip(),
                datetime_to_storage(payload.departure_at),
                payload.price_cents,
                payload.seats_available,
                payload.max_time_gap_minutes,
                utc_now(),
            ),
        )
        return one(connection, "SELECT * FROM rides WHERE id = ?", (cursor.lastrowid,))


@router.get("/events/{event_id}/rides")
def list_rides(event_id: int, viewer_id: int = Query(gt=0)) -> list[dict]:
    with db_connection() as connection:
        _enabled_event(connection, event_id, "carpool_enabled", viewer_id)
        return many(connection, "SELECT * FROM rides WHERE event_id = ? ORDER BY departure_at, id", (event_id,))


@router.get("/rides/{ride_id}")
def get_ride(ride_id: int, viewer_id: int = Query(gt=0)) -> dict:
    with db_connection() as connection:
        ride = require_ride(connection, ride_id)
        _enabled_event(connection, ride["event_id"], "carpool_enabled", viewer_id)
        return ride


@router.patch("/rides/{ride_id}")
def update_ride(ride_id: int, payload: RideUpdate) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("driver_id", None)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Indiquez des champs non nuls à modifier.")
    with db_connection(write=True) as connection:
        ride = require_ride(connection, ride_id)
        event = _enabled_event(connection, ride["event_id"], "carpool_enabled", payload.driver_id)
        if payload.driver_id != ride["driver_id"]:
            require_event_organizer(connection, ride["event_id"], payload.driver_id)
        departure_at = changes.get("departure_at", datetime.fromisoformat(ride["departure_at"]))
        if departure_at >= datetime.fromisoformat(event["starts_at"]):
            raise HTTPException(status_code=422, detail="Le départ doit précéder le début de l’événement.")
        if "departure_location" in changes:
            changes["departure_location"] = changes["departure_location"].strip()
        if "departure_at" in changes:
            changes["departure_at"] = datetime_to_storage(changes["departure_at"])
        columns = ", ".join(f"{key} = ?" for key in changes)
        connection.execute(f"UPDATE rides SET {columns} WHERE id = ?", (*changes.values(), ride_id))
        return one(connection, "SELECT * FROM rides WHERE id = ?", (ride_id,))


@router.delete("/rides/{ride_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ride(ride_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        ride = require_ride(connection, ride_id)
        _enabled_event(connection, ride["event_id"], "carpool_enabled", actor_id)
        if actor_id != ride["driver_id"]:
            require_event_organizer(connection, ride["event_id"], actor_id)
        connection.execute("DELETE FROM rides WHERE id = ?", (ride_id,))
