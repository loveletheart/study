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
from app.common.errors.handlers import register_exception_handlers
from app.common.errors.openapi import error_code_table, error_responses
from app.common.responses import ApiResponse
from app.outfits.presentation.router import router as outfits_router
from app.users.presentation.router import router as users_router
from app.weather.presentation.router import router as weather_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 DB 테이블 준비"""
    initialize_database()
    yield


app = FastAPI(
    title=get_settings().app_name,
    lifespan=lifespan,
    description=(
        "날씨 조회, 옷차림 추천과 사용자 관리 API입니다.\n\n"
        "## 공통 응답\n\n"
        "응답 형식: `code`, `message`, `data`, `details`.\n\n"
        "성공 시 code는 SUCCESS이고 data에 결과가 담깁니다. 실패 시 data는 null입니다.\n\n"
        "### 오류 코드 목록\n\n" + error_code_table()
    ),
    openapi_tags=[
        {"name": "weather", "description": "국내 지역 검색과 한국 시간 기준 오늘·7일 예보 조회"},
        {"name": "outfits", "description": "날씨 기반 오늘·7일 옷차림과 추천 이유"},
        {"name": "users", "description": "사용자 등록과 UUID 기반 조회"},
        {"name": "system", "description": "서비스 안내와 서버 응답 상태 확인"},
    ],
)
register_exception_handlers(app)
app.include_router(users_router, prefix="/api/v1")
app.include_router(weather_router, prefix="/api/v1")
app.include_router(outfits_router, prefix="/api/v1")


@app.get("/", summary="서비스 기본 안내", description="서비스 안내 메시지를 반환합니다.", tags=["system"], responses=error_responses(include_validation=False))
async def root() -> ApiResponse[dict[str, str]]:
    """서비스 안내 메시지 반환"""
    return ApiResponse(data={"message": "Hello FastAPI"})


@app.get("/health", summary="서버 응답 상태 확인", description="앱의 응답 여부만 확인합니다. DB·외부 API는 검사하지 않습니다.", tags=["system"], responses=error_responses(include_validation=False))
async def health() -> ApiResponse[dict[str, str]]:
    """서버 응답 상태 확인"""
    return ApiResponse(data={"status": "ok"})
