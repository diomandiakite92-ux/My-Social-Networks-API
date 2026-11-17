from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..common import many, one, require_event, require_event_organizer, require_event_visible, require_ticket_type
from ..database import db_connection, utc_now
from ..schemas import TicketPurchase, TicketTypeCreate, TicketTypeUpdate


router = APIRouter(tags=["Billetterie"])


def _ticket_type_detail(connection, ticket_type: dict) -> dict:
    result = dict(ticket_type)
    result["sold"] = connection.execute(
        "SELECT COUNT(*) AS count FROM tickets WHERE ticket_type_id = ?",
        (ticket_type["id"],),
    ).fetchone()["count"]
    result["available"] = result["quantity"] - result["sold"]
    return result


@router.post("/events/{event_id}/ticket-types", status_code=status.HTTP_201_CREATED)
def create_ticket_type(event_id: int, payload: TicketTypeCreate) -> dict:
    with db_connection(write=True) as connection:
        event = require_event_organizer(connection, event_id, payload.organizer_id)
        if event["visibility"] != "public":
            raise HTTPException(status_code=409, detail="La billetterie est réservée aux événements publics.")
        cursor = connection.execute(
            "INSERT INTO ticket_types (event_id, name, price_cents, quantity) VALUES (?, ?, ?, ?)",
            (event_id, payload.name.strip(), payload.price_cents, payload.quantity),
        )
        return _ticket_type_detail(connection, one(connection, "SELECT * FROM ticket_types WHERE id = ?", (cursor.lastrowid,)))


@router.get("/events/{event_id}/ticket-types")
def list_ticket_types(event_id: int, viewer_id: int | None = Query(default=None, gt=0)) -> list[dict]:
    with db_connection() as connection:
        event = require_event_visible(connection, event_id, viewer_id)
        if event["visibility"] != "public":
            raise HTTPException(status_code=404, detail="Billetterie introuvable.")
        return [
            _ticket_type_detail(connection, item)
            for item in many(connection, "SELECT * FROM ticket_types WHERE event_id = ? ORDER BY id", (event_id,))
        ]


@router.get("/ticket-types/{ticket_type_id}")
def get_ticket_type(ticket_type_id: int, viewer_id: int | None = Query(default=None, gt=0)) -> dict:
    with db_connection() as connection:
        ticket_type = require_ticket_type(connection, ticket_type_id)
        require_event_visible(connection, ticket_type["event_id"], viewer_id)
        return _ticket_type_detail(connection, ticket_type)


@router.patch("/ticket-types/{ticket_type_id}")
def update_ticket_type(
    ticket_type_id: int,
    payload: TicketTypeUpdate,
    actor_id: int = Query(gt=0),
) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Indiquez au moins un champ à modifier.")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Un champ de billet ne peut pas être nul.")
    with db_connection(write=True) as connection:
        ticket_type = require_ticket_type(connection, ticket_type_id)
        require_event_organizer(connection, ticket_type["event_id"], actor_id)
        sold = connection.execute(
            "SELECT COUNT(*) AS count FROM tickets WHERE ticket_type_id = ?",
            (ticket_type_id,),
        ).fetchone()["count"]
        if "quantity" in changes and changes["quantity"] < sold:
            raise HTTPException(status_code=409, detail="La quantité ne peut pas être inférieure aux billets déjà vendus.")
        if "name" in changes:
            changes["name"] = changes["name"].strip()
        columns = ", ".join(f"{key} = ?" for key in changes)
        connection.execute(f"UPDATE ticket_types SET {columns} WHERE id = ?", (*changes.values(), ticket_type_id))
        return _ticket_type_detail(connection, one(connection, "SELECT * FROM ticket_types WHERE id = ?", (ticket_type_id,)))


@router.delete("/ticket-types/{ticket_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket_type(ticket_type_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        ticket_type = require_ticket_type(connection, ticket_type_id)
        require_event_organizer(connection, ticket_type["event_id"], actor_id)
        sold = connection.execute(
            "SELECT COUNT(*) AS count FROM tickets WHERE ticket_type_id = ?",
            (ticket_type_id,),
        ).fetchone()["count"]
        if sold:
            raise HTTPException(status_code=409, detail="Un type de billet vendu ne peut pas être supprimé.")
        connection.execute("DELETE FROM ticket_types WHERE id = ?", (ticket_type_id,))


@router.post("/events/{event_id}/ticket-types/{ticket_type_id}/tickets", status_code=status.HTTP_201_CREATED)
def purchase_ticket(event_id: int, ticket_type_id: int, payload: TicketPurchase) -> dict:
    with db_connection(write=True) as connection:
        event = require_event(connection, event_id)
        if event["visibility"] != "public":
            raise HTTPException(status_code=409, detail="La billetterie est réservée aux événements publics.")
        ticket_type = require_ticket_type(connection, ticket_type_id)
        if ticket_type["event_id"] != event_id:
            raise HTTPException(status_code=404, detail="Type de billet introuvable pour cet événement.")
        existing = connection.execute(
            "SELECT 1 FROM tickets WHERE event_id = ? AND buyer_email = ? COLLATE NOCASE",
            (event_id, payload.email),
        ).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Cette adresse e-mail possède déjà un billet pour cet événement.")
        sold = connection.execute(
            "SELECT COUNT(*) AS count FROM tickets WHERE ticket_type_id = ?",
            (ticket_type_id,),
        ).fetchone()["count"]
        if sold >= ticket_type["quantity"]:
            raise HTTPException(status_code=409, detail="Ce type de billet est épuisé.")
        cursor = connection.execute(
            "INSERT INTO tickets (event_id, ticket_type_id, buyer_first_name, buyer_last_name, buyer_email, "
            "buyer_address, purchased_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                ticket_type_id,
                payload.first_name,
                payload.last_name,
                payload.email,
                payload.address,
                utc_now(),
            ),
        )
        return one(connection, "SELECT * FROM tickets WHERE id = ?", (cursor.lastrowid,))


@router.get("/events/{event_id}/tickets")
def list_event_tickets(event_id: int, organizer_id: int = Query(gt=0)) -> list[dict]:
    with db_connection() as connection:
        require_event_organizer(connection, event_id, organizer_id)
        return many(
            connection,
            "SELECT t.*, tt.name AS ticket_type_name, tt.price_cents FROM tickets t "
            "JOIN ticket_types tt ON tt.id = t.ticket_type_id WHERE t.event_id = ? ORDER BY t.purchased_at",
            (event_id,),
        )


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, organizer_id: int = Query(gt=0)) -> dict:
    with db_connection() as connection:
        ticket = one(connection, "SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        require_event_organizer(connection, ticket["event_id"], organizer_id)
        return ticket


@router.delete("/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket(ticket_id: int, organizer_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        ticket = one(connection, "SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        require_event_organizer(connection, ticket["event_id"], organizer_id)
        connection.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
