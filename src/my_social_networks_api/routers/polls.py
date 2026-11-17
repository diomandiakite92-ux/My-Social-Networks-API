from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..common import many, one, require_event_member, require_event_organizer, require_event_participant, require_event_visible, require_poll
from ..database import db_connection, utc_now
from ..schemas import (
    PollCreate,
    PollOptionCreate,
    PollOptionUpdate,
    PollQuestionCreate,
    PollQuestionUpdate,
    PollResponseCreate,
    PollUpdate,
)


router = APIRouter(tags=["Sondages"])


def _poll_detail(connection, poll: dict) -> dict:
    result = dict(poll)
    questions = many(
        connection,
        "SELECT * FROM poll_questions WHERE poll_id = ? ORDER BY id",
        (poll["id"],),
    )
    for question in questions:
        question["options"] = many(
            connection,
            "SELECT * FROM poll_options WHERE question_id = ? ORDER BY id",
            (question["id"],),
        )
    result["questions"] = questions
    return result


def _create_question(connection, poll_id: int, prompt: str, options: list) -> int:
    cursor = connection.execute(
        "INSERT INTO poll_questions (poll_id, prompt) VALUES (?, ?)",
        (poll_id, prompt.strip()),
    )
    question_id = cursor.lastrowid
    connection.executemany(
        "INSERT INTO poll_options (question_id, label) VALUES (?, ?)",
        [(question_id, option.label.strip()) for option in options],
    )
    return question_id


@router.post("/events/{event_id}/polls", status_code=status.HTTP_201_CREATED)
def create_poll(event_id: int, payload: PollCreate) -> dict:
    with db_connection(write=True) as connection:
        require_event_organizer(connection, event_id, payload.creator_id)
        cursor = connection.execute(
            "INSERT INTO polls (event_id, title, created_by, created_at) VALUES (?, ?, ?, ?)",
            (event_id, payload.title.strip(), payload.creator_id, utc_now()),
        )
        poll_id = cursor.lastrowid
        for question in payload.questions:
            _create_question(connection, poll_id, question.prompt, question.options)
        return _poll_detail(connection, one(connection, "SELECT * FROM polls WHERE id = ?", (poll_id,)))


@router.get("/events/{event_id}/polls")
def list_event_polls(
    event_id: int,
    viewer_id: int | None = Query(default=None, gt=0),
) -> list[dict]:
    with db_connection() as connection:
        require_event_visible(connection, event_id, viewer_id)
        return [
            _poll_detail(connection, poll)
            for poll in many(connection, "SELECT * FROM polls WHERE event_id = ? ORDER BY id", (event_id,))
        ]


@router.get("/polls/{poll_id}")
def get_poll(poll_id: int, viewer_id: int | None = Query(default=None, gt=0)) -> dict:
    with db_connection() as connection:
        poll = require_poll(connection, poll_id)
        require_event_visible(connection, poll["event_id"], viewer_id)
        return _poll_detail(connection, poll)


@router.patch("/polls/{poll_id}")
def update_poll(poll_id: int, payload: PollUpdate, actor_id: int = Query(gt=0)) -> dict:
    if payload.title is None or not payload.title.strip():
        raise HTTPException(status_code=422, detail="Le titre du sondage est obligatoire.")
    with db_connection(write=True) as connection:
        poll = require_poll(connection, poll_id)
        require_event_organizer(connection, poll["event_id"], actor_id)
        connection.execute("UPDATE polls SET title = ? WHERE id = ?", (payload.title.strip(), poll_id))
        return _poll_detail(connection, one(connection, "SELECT * FROM polls WHERE id = ?", (poll_id,)))


@router.delete("/polls/{poll_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_poll(poll_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        poll = require_poll(connection, poll_id)
        require_event_organizer(connection, poll["event_id"], actor_id)
        connection.execute("DELETE FROM polls WHERE id = ?", (poll_id,))


@router.post("/polls/{poll_id}/questions", status_code=status.HTTP_201_CREATED)
def create_question(poll_id: int, payload: PollQuestionCreate, actor_id: int = Query(gt=0)) -> dict:
    with db_connection(write=True) as connection:
        poll = require_poll(connection, poll_id)
        require_event_organizer(connection, poll["event_id"], actor_id)
        question_id = _create_question(connection, poll_id, payload.prompt, payload.options)
        question = one(connection, "SELECT * FROM poll_questions WHERE id = ?", (question_id,))
        question["options"] = many(connection, "SELECT * FROM poll_options WHERE question_id = ? ORDER BY id", (question_id,))
        return question


@router.patch("/poll-questions/{question_id}")
def update_question(question_id: int, payload: PollQuestionUpdate, actor_id: int = Query(gt=0)) -> dict:
    with db_connection(write=True) as connection:
        question = one(connection, "SELECT * FROM poll_questions WHERE id = ?", (question_id,))
        poll = require_poll(connection, question["poll_id"])
        require_event_organizer(connection, poll["event_id"], actor_id)
        connection.execute("UPDATE poll_questions SET prompt = ? WHERE id = ?", (payload.prompt.strip(), question_id))
        result = one(connection, "SELECT * FROM poll_questions WHERE id = ?", (question_id,))
        result["options"] = many(connection, "SELECT * FROM poll_options WHERE question_id = ? ORDER BY id", (question_id,))
        return result


@router.delete("/poll-questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(question_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        question = one(connection, "SELECT * FROM poll_questions WHERE id = ?", (question_id,))
        poll = require_poll(connection, question["poll_id"])
        require_event_organizer(connection, poll["event_id"], actor_id)
        question_count = connection.execute(
            "SELECT COUNT(*) AS count FROM poll_questions WHERE poll_id = ?",
            (poll["id"],),
        ).fetchone()["count"]
        if question_count <= 1:
            raise HTTPException(status_code=409, detail="Un sondage doit conserver au moins une question.")
        connection.execute("DELETE FROM poll_questions WHERE id = ?", (question_id,))


@router.post("/poll-questions/{question_id}/options", status_code=status.HTTP_201_CREATED)
def create_option(question_id: int, payload: PollOptionCreate, actor_id: int = Query(gt=0)) -> dict:
    with db_connection(write=True) as connection:
        question = one(connection, "SELECT * FROM poll_questions WHERE id = ?", (question_id,))
        poll = require_poll(connection, question["poll_id"])
        require_event_organizer(connection, poll["event_id"], actor_id)
        cursor = connection.execute(
            "INSERT INTO poll_options (question_id, label) VALUES (?, ?)",
            (question_id, payload.label.strip()),
        )
        return one(connection, "SELECT * FROM poll_options WHERE id = ?", (cursor.lastrowid,))


@router.patch("/poll-options/{option_id}")
def update_option(option_id: int, payload: PollOptionUpdate, actor_id: int = Query(gt=0)) -> dict:
    with db_connection(write=True) as connection:
        option = one(connection, "SELECT * FROM poll_options WHERE id = ?", (option_id,))
        question = one(connection, "SELECT * FROM poll_questions WHERE id = ?", (option["question_id"],))
        poll = require_poll(connection, question["poll_id"])
        require_event_organizer(connection, poll["event_id"], actor_id)
        connection.execute("UPDATE poll_options SET label = ? WHERE id = ?", (payload.label.strip(), option_id))
        return one(connection, "SELECT * FROM poll_options WHERE id = ?", (option_id,))


@router.delete("/poll-options/{option_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_option(option_id: int, actor_id: int = Query(gt=0)) -> None:
    with db_connection(write=True) as connection:
        option = one(connection, "SELECT * FROM poll_options WHERE id = ?", (option_id,))
        question = one(connection, "SELECT * FROM poll_questions WHERE id = ?", (option["question_id"],))
        poll = require_poll(connection, question["poll_id"])
        require_event_organizer(connection, poll["event_id"], actor_id)
        option_count = connection.execute(
            "SELECT COUNT(*) AS count FROM poll_options WHERE question_id = ?",
            (question["id"],),
        ).fetchone()["count"]
        answer_count = connection.execute(
            "SELECT COUNT(*) AS count FROM poll_answers WHERE option_id = ?",
            (option_id,),
        ).fetchone()["count"]
        if option_count <= 2:
            raise HTTPException(status_code=409, detail="Une question doit conserver au moins deux choix.")
        if answer_count:
            raise HTTPException(status_code=409, detail="Un choix déjà sélectionné ne peut pas être supprimé.")
        connection.execute("DELETE FROM poll_options WHERE id = ?", (option_id,))


@router.post("/polls/{poll_id}/responses", status_code=status.HTTP_201_CREATED)
def submit_poll_response(poll_id: int, payload: PollResponseCreate) -> dict:
    with db_connection(write=True) as connection:
        poll = require_poll(connection, poll_id)
        require_event_participant(connection, poll["event_id"], payload.participant_id)
        questions = many(connection, "SELECT id FROM poll_questions WHERE poll_id = ?", (poll_id,))
        expected_question_ids = {question["id"] for question in questions}
        submitted_question_ids = [answer.question_id for answer in payload.answers]
        if len(submitted_question_ids) != len(set(submitted_question_ids)):
            raise HTTPException(status_code=422, detail="Une seule réponse est autorisée par question.")
        if set(submitted_question_ids) != expected_question_ids:
            raise HTTPException(status_code=422, detail="Une réponse doit être fournie pour chaque question du sondage.")
        for answer in payload.answers:
            selected = connection.execute(
                "SELECT 1 FROM poll_options po JOIN poll_questions pq ON pq.id = po.question_id "
                "WHERE po.id = ? AND pq.id = ? AND pq.poll_id = ?",
                (answer.option_id, answer.question_id, poll_id),
            ).fetchone()
            if selected is None:
                raise HTTPException(status_code=422, detail="Le choix sélectionné n’appartient pas à cette question.")
        connection.executemany(
            "INSERT INTO poll_answers (question_id, participant_id, option_id, answered_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(question_id, participant_id) DO UPDATE SET option_id = excluded.option_id, "
            "answered_at = excluded.answered_at",
            [
                (answer.question_id, payload.participant_id, answer.option_id, utc_now())
                for answer in payload.answers
            ],
        )
        return get_participant_answers(connection, poll_id, payload.participant_id)


def get_participant_answers(connection, poll_id: int, participant_id: int) -> dict:
    return {
        "poll_id": poll_id,
        "participant_id": participant_id,
        "answers": many(
            connection,
            "SELECT pq.id AS question_id, pq.prompt, po.id AS option_id, po.label, pa.answered_at "
            "FROM poll_answers pa JOIN poll_questions pq ON pq.id = pa.question_id "
            "JOIN poll_options po ON po.id = pa.option_id "
            "WHERE pq.poll_id = ? AND pa.participant_id = ? ORDER BY pq.id",
            (poll_id, participant_id),
        ),
    }


@router.get("/polls/{poll_id}/responses/{participant_id}")
def read_participant_answers(poll_id: int, participant_id: int, viewer_id: int = Query(gt=0)) -> dict:
    with db_connection() as connection:
        poll = require_poll(connection, poll_id)
        require_event_member(connection, poll["event_id"], viewer_id)
        require_event_participant(connection, poll["event_id"], participant_id)
        return get_participant_answers(connection, poll_id, participant_id)


@router.get("/polls/{poll_id}/results")
def poll_results(poll_id: int, viewer_id: int = Query(gt=0)) -> dict:
    with db_connection() as connection:
        poll = require_poll(connection, poll_id)
        require_event_member(connection, poll["event_id"], viewer_id)
        questions = many(connection, "SELECT * FROM poll_questions WHERE poll_id = ? ORDER BY id", (poll_id,))
        for question in questions:
            question["options"] = many(
                connection,
                "SELECT po.id, po.label, COUNT(pa.participant_id) AS votes "
                "FROM poll_options po LEFT JOIN poll_answers pa ON pa.option_id = po.id "
                "WHERE po.question_id = ? GROUP BY po.id, po.label ORDER BY po.id",
                (question["id"],),
            )
        return {"poll_id": poll_id, "title": poll["title"], "questions": questions}
