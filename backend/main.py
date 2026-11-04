from contextlib import asynccontextmanager

# The editor's "Run Python File" button also uses the same environment setup.
# This must run before importing any third-party application dependency.
if __name__ == "__main__":
    from pathlib import Path
    from subprocess import call

    raise SystemExit(
        call(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path(__file__).resolve().parents[1] / "run.ps1"),
            ]
        )
    )

from fastapi import FastAPI

from app.common.config import get_settings
from app.common.database import initialize_database
from app.users.presentation.router import router as users_router
from app.weather.presentation.router import router as weather_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(users_router, prefix="/api/v1")
app.include_router(weather_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello FastAPI"}


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
