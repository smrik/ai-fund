from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TranscriptParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    speaker_name: str = Field(min_length=1)
    speaker_role: str = ""
    start_time: str | None = None
    end_time: str | None = None
    text: str = Field(min_length=1)
    deep_link_url: str | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.strptime(value, "%H:%M:%S")
        except ValueError as exc:
            raise ValueError("time must be HH:MM:SS") from exc
        return value


class TranscriptDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1)
    source: Literal["quartr"]
    event_id: str = Field(min_length=1)
    event_title: str = Field(min_length=1)
    event_date: str
    fiscal_quarter: int | None = Field(default=None, ge=1, le=4)
    fiscal_year: int | None = Field(default=None, ge=1900)
    document_id: str = Field(min_length=1)
    document_url: str = Field(min_length=1)
    transcript_source: Literal["indexed", "live"]
    paragraphs: list[TranscriptParagraph] = Field(min_length=1)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("event_date")
    @classmethod
    def validate_event_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("event_date must be YYYY-MM-DD") from exc
        return parsed.isoformat()
