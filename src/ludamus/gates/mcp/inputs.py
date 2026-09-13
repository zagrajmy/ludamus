from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from django.core.files.base import ContentFile
from pydantic import BaseModel, Field, StringConstraints, field_validator

from ludamus.gates.mcp.registry import ToolError
from ludamus.gates.uploads import upload_error

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.core.files.base import File

type NonBlankName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class EmptyInput(BaseModel):
    pass


def require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("must be timezone-aware")
    return value


class AwareDatetimeRange(BaseModel):
    start_time: datetime = Field(
        description="Timezone-aware ISO-8601 start (naive values are rejected)"
    )
    end_time: datetime = Field(
        description="Timezone-aware ISO-8601 end; must be after start_time"
    )

    @field_validator("start_time", "end_time")
    @classmethod
    def _aware_datetimes(cls, value: datetime) -> datetime:
        return require_aware_datetime(value)


class EventIdInput(BaseModel):
    event_id: int = Field(description="Event primary key (see list_events / get_event)")


class ImageUploadInput(BaseModel):
    filename: NonBlankName = Field(description="Original file name, with extension")
    content_base64: str = Field(
        description=(
            "File content, standard base64. Decoded size is capped at 8 MB, and "
            "the HTTP body cap applies to the whole request."
        )
    )

    def validated_upload(
        self, validate: Callable[[File[bytes]], None]
    ) -> ContentFile[bytes]:
        try:
            content = base64.b64decode(self.content_base64, validate=True)
        except binascii.Error as error:
            message = f"content_base64 is not valid base64: {error}"
            raise ToolError(message) from error
        if not content:
            raise ToolError("content_base64 decoded to an empty file")
        upload = ContentFile(content, name=self.filename)
        if (problem := upload_error(validate, upload)) is not None:
            raise ToolError(problem)
        return upload
