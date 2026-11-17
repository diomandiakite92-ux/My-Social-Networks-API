from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .database import initialize_database
from .routers import events, extras, groups, interactions, polls, ticketing, users


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="My Social Networks API",
    description="API de gestion d’événements, de groupes et de leurs services associés.",
    version="2.0.0",
    lifespan=lifespan,
)

for api_router in (
    users.router,
    events.router,
    groups.router,
    interactions.router,
    polls.router,
    ticketing.router,
    extras.router,
):
    app.include_router(api_router)


@app.get("/health", tags=["Système"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(sqlite3.IntegrityError)
async def handle_integrity_error(_: Request, __: sqlite3.IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": "Cette opération entre en conflit avec une donnée ou une règle existante."},
    )


def main() -> None:
    import uvicorn

    uvicorn.run("my_social_networks_api.main:app", host="127.0.0.1", port=8000)
