import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(ApiModel):
    """Public view of a user. Never includes the password hash or internal flags."""

    id: uuid.UUID
    username: str
    display_name: str


class SessionOut(ApiModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime
