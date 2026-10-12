from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.core.config import Settings

app = FastAPI(title=Settings().app_name)
app.include_router(health_router)
app.include_router(chat_router)
