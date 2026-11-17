"""Request schemas and basic validation for the API."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _email(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
        raise ValueError("Une adresse e-mail valide est requise.")
    return normalized


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _nonempty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Ce champ ne peut pas être vide.")
    return value


def _optional_nonempty(value: str | None) -> str | None:
    return _nonempty(value) if value is not None else None


class UserCreate(StrictModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=254)

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_names(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Ce champ ne peut pas être vide.")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _email(value)


class UserUpdate(StrictModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_optional_names(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Ce champ ne peut pas être vide.")
        return value

    @field_validator("email")
    @classmethod
    def normalize_optional_email(cls, value: str | None) -> str | None:
        return _email(value) if value is not None else None


class EventCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    starts_at: datetime
    ends_at: datetime
    location: str = Field(min_length=1, max_length=500)
    cover_image_url: str | None = Field(default=None, max_length=2000)
    visibility: Literal["public", "private"] = "public"
    creator_id: int = Field(gt=0)
    organizer_ids: list[int] = Field(default_factory=list)
    participant_ids: list[int] = Field(default_factory=list)
    group_id: int | None = Field(default=None, gt=0)
    shopping_list_enabled: bool = False
    carpool_enabled: bool = False

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_dates(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_validator("name", "location")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Ce champ ne peut pas être vide.")
        return value

    @model_validator(mode="after")
    def check_dates(self) -> "EventCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("La date de fin doit être postérieure à la date de début.")
        return self


class EventUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location: str | None = Field(default=None, min_length=1, max_length=500)
    cover_image_url: str | None = Field(default=None, max_length=2000)
    visibility: Literal["public", "private"] | None = None
    shopping_list_enabled: bool | None = None
    carpool_enabled: bool | None = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_optional_dates(cls, value: datetime | None) -> datetime | None:
        return _utc_datetime(value) if value is not None else None

    @field_validator("name", "location")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Ce champ ne peut pas être vide.")
        return value


class GroupCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    icon_url: str | None = Field(default=None, max_length=2000)
    cover_image_url: str | None = Field(default=None, max_length=2000)
    visibility: Literal["public", "private", "secret"]
    allow_member_posts: bool = False
    allow_member_events: bool = False
    creator_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def strip_group_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le nom du groupe ne peut pas être vide.")
        return value


class GroupUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    icon_url: str | None = Field(default=None, max_length=2000)
    cover_image_url: str | None = Field(default=None, max_length=2000)
    visibility: Literal["public", "private", "secret"] | None = None
    allow_member_posts: bool | None = None
    allow_member_events: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_optional_group_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Le nom du groupe ne peut pas être vide.")
        return value


class GroupMemberRoleUpdate(StrictModel):
    role: Literal["member", "admin"]


class TextCreate(StrictModel):
    author_id: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le message ne peut pas être vide.")
        return value


class TextUpdate(StrictModel):
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le message ne peut pas être vide.")
        return value


class AlbumCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    creator_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _nonempty(value)


class AlbumUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return _optional_nonempty(value)


class PhotoCreate(StrictModel):
    participant_id: int = Field(gt=0)
    image_url: str = Field(min_length=1, max_length=2000)
    caption: str = Field(default="", max_length=2000)

    @field_validator("image_url")
    @classmethod
    def normalize_image_url(cls, value: str) -> str:
        return _nonempty(value)

    @field_validator("caption")
    @classmethod
    def normalize_caption(cls, value: str) -> str:
        return value.strip()


class PhotoUpdate(StrictModel):
    image_url: str | None = Field(default=None, min_length=1, max_length=2000)
    caption: str | None = Field(default=None, max_length=2000)

    @field_validator("image_url")
    @classmethod
    def normalize_optional_image_url(cls, value: str | None) -> str | None:
        return _optional_nonempty(value)

    @field_validator("caption")
    @classmethod
    def normalize_optional_caption(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class PollOptionInput(StrictModel):
    label: str = Field(min_length=1, max_length=500)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return _nonempty(value)


class PollQuestionInput(StrictModel):
    prompt: str = Field(min_length=1, max_length=1000)
    options: list[PollOptionInput] = Field(min_length=2)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return _nonempty(value)

    @field_validator("options")
    @classmethod
    def unique_options(cls, values: list[PollOptionInput]) -> list[PollOptionInput]:
        labels = [value.label.strip().casefold() for value in values]
        if len(labels) != len(set(labels)):
            raise ValueError("Les choix d’une question doivent être uniques.")
        return values


class PollCreate(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    creator_id: int = Field(gt=0)
    questions: list[PollQuestionInput] = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return _nonempty(value)


class PollUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)


class PollQuestionCreate(StrictModel):
    prompt: str = Field(min_length=1, max_length=1000)
    options: list[PollOptionInput] = Field(min_length=2)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return _nonempty(value)


class PollQuestionUpdate(StrictModel):
    prompt: str = Field(min_length=1, max_length=1000)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return _nonempty(value)


class PollOptionCreate(StrictModel):
    label: str = Field(min_length=1, max_length=500)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return _nonempty(value)


class PollOptionUpdate(StrictModel):
    label: str = Field(min_length=1, max_length=500)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return _nonempty(value)


class PollAnswerInput(StrictModel):
    question_id: int = Field(gt=0)
    option_id: int = Field(gt=0)


class PollResponseCreate(StrictModel):
    participant_id: int = Field(gt=0)
    answers: list[PollAnswerInput] = Field(min_length=1)


class TicketTypeCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    price_cents: int = Field(ge=0)
    quantity: int = Field(ge=1)
    organizer_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _nonempty(value)


class TicketTypeUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    price_cents: int | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        return _optional_nonempty(value)


class TicketPurchase(StrictModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=254)
    address: str = Field(min_length=1, max_length=1000)

    @field_validator("first_name", "last_name", "address")
    @classmethod
    def strip_buyer_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Ce champ ne peut pas être vide.")
        return value

    @field_validator("email")
    @classmethod
    def normalize_buyer_email(cls, value: str) -> str:
        return _email(value)


class ShoppingItemCreate(StrictModel):
    user_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1)
    arrival_at: datetime

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _nonempty(value)

    @field_validator("arrival_at")
    @classmethod
    def normalize_arrival(cls, value: datetime) -> datetime:
        return _utc_datetime(value)


class ShoppingItemUpdate(StrictModel):
    user_id: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: int | None = Field(default=None, ge=1)
    arrival_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        return _optional_nonempty(value)

    @field_validator("arrival_at")
    @classmethod
    def normalize_optional_arrival(cls, value: datetime | None) -> datetime | None:
        return _utc_datetime(value) if value is not None else None


class RideCreate(StrictModel):
    driver_id: int = Field(gt=0)
    departure_location: str = Field(min_length=1, max_length=500)
    departure_at: datetime
    price_cents: int = Field(ge=0)
    seats_available: int = Field(ge=1)
    max_time_gap_minutes: int = Field(ge=0)

    @field_validator("departure_location")
    @classmethod
    def normalize_location(cls, value: str) -> str:
        return _nonempty(value)

    @field_validator("departure_at")
    @classmethod
    def normalize_departure(cls, value: datetime) -> datetime:
        return _utc_datetime(value)


class RideUpdate(StrictModel):
    driver_id: int = Field(gt=0)
    departure_location: str | None = Field(default=None, min_length=1, max_length=500)
    departure_at: datetime | None = None
    price_cents: int | None = Field(default=None, ge=0)
    seats_available: int | None = Field(default=None, ge=1)
    max_time_gap_minutes: int | None = Field(default=None, ge=0)

    @field_validator("departure_location")
    @classmethod
    def normalize_optional_location(cls, value: str | None) -> str | None:
        return _optional_nonempty(value)

    @field_validator("departure_at")
    @classmethod
    def normalize_optional_departure(cls, value: datetime | None) -> datetime | None:
        return _utc_datetime(value) if value is not None else None
