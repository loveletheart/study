from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.common.config import get_settings
from app.common.database import initialize_database
from app.users.presentation.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(users_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello FastAPI"}


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
