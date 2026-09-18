from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PersonDraft(BaseModel):
    display_name: str
    relation: str | None = None
    aliases: str | None = None
    birthday_day: int | None = None
    birthday_month: int | None = None
    birthday_year: int | None = None
    attributes: list[dict[str, str]] = Field(default_factory=list)


class ReminderRecurringDraft(BaseModel):
    title: str
    body: str | None = None
    rrule: str
    dtstart: str
    time_of_day: str = "10:00"
    human_summary: str = ""


class ReminderOneShotDraft(BaseModel):
    title: str
    body: str | None = None
    fire_at: str


class EntityTypeDraft(BaseModel):
    name: str
    title: str
    description: str | None = None
    fields: list[dict[str, Any]] = Field(default_factory=list)


class AssistantReply(BaseModel):
    """Структурированный ответ модели для бота."""

    mode: Literal["chat", "propose_action"] = "chat"
    message: str
    action_type: str | None = None
    # payload зависит от action_type; валидируем при применении
    payload: dict[str, Any] = Field(default_factory=dict)


ACTION_TYPES = {
    "upsert_person",
    "create_reminder_one_shot",
    "create_reminder_recurring",
    "create_entity_type",
}
