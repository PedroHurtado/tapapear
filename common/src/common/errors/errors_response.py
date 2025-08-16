from typing import Optional, Union, Sequence, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class ErrorResponse(BaseModel):
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        )
    )
    status: int
    error: str
    exception: Optional[str] = None
    message: Union[str, Sequence[Any]]
    path: str
