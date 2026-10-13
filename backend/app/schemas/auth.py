from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.auth.security import normalize_email


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return normalize_email(value)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_seconds: int


class UserPublic(BaseModel):
    id: int
    email: str
    role: Literal["admin", "staff"]
    is_active: bool

    model_config = {"from_attributes": True}
