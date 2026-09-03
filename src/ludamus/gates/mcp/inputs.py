from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

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
