from pydantic import BaseModel


class UserRegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str


class UserLoginRequest(BaseModel):
    account: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserProfileUpdateRequest(BaseModel):
    display_name: str
    email: str | None = None


class UserProfileResponse(BaseModel):
    id: str
    display_name: str
    email: str | None = None


class AuthResponseData(BaseModel):
    access_token: str
    refresh_token: str
    user_profile: UserProfileResponse
