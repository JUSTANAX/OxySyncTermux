import hmac
import hashlib
from fastapi import FastAPI
from pydantic import BaseModel
from config import SERVER_SECRET, MASTER_KEY

app = FastAPI(docs_url=None, redoc_url=None)


class AuthRequest(BaseModel):
    token: str
    device_id: str


def derive_key(token: str, device_id: str) -> str:
    """Уникальный ключ для конкретного устройства + токена."""
    raw = f"{token}:{device_id}:{MASTER_KEY}"
    return hmac.new(
        SERVER_SECRET.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()


@app.post("/api/v1/auth")
async def authenticate(req: AuthRequest):
    # AUTH TEMPORARILY DISABLED
    return {
        "key": "bypass",
        "plan": "premium",
        "username": "",
        "expires_at": None,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
