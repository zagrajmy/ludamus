from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints, field_validator

type NonBlankName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class EmptyInput(BaseModel):
    pass


def require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        message = f"{field} must be timezone-aware"
        raise ValueError(message)
    return value


class AwareDatetimeRange(BaseModel):
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def _aware_datetimes(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, field="datetime")
