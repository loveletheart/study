# 표준 라이브러리
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

# 편집기의 "Run Python File" 버튼으로 실행할 때도 동일한 환경 준비 과정을 거칩니다.
# 외부 패키지를 가져오기 전에 실행 스크립트로 위임해야 합니다.
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

# 외부 라이브러리
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# 프로젝트 모듈
from app.common.config import get_settings
from app.common.database import initialize_database
from app.common.errors.handlers import register_exception_handlers
from app.common.errors.openapi import error_code_table, error_responses
from app.common.responses import ApiResponse
from app.outfits.presentation.router import router as outfits_router
from app.outfits.bootstrap import (
    get_cached_outfit_service,
    get_personalized_outfit_cache,
    get_weekly_outfit_batch,
)
from app.outfits.infrastructure.jobs import OutfitRefreshWorker
from app.users.presentation.router import router as users_router
from app.weather.presentation.router import router as weather_router


# 서버 시작·종료 처리
@asynccontextmanager
async def lifespan(app: FastAPI):
    """DB 준비와 저장된 지역의 추천 주기 갱신 시작·종료"""
    initialize_database()
    worker = OutfitRefreshWorker(get_cached_outfit_service())
    personal_worker = OutfitRefreshWorker(get_personalized_outfit_cache())
    weekly_worker = OutfitRefreshWorker(get_weekly_outfit_batch())
    worker.start()
    personal_worker.start()
    weekly_worker.start()
    try:
        yield
    finally:
        weekly_worker.stop()
        personal_worker.stop()
        worker.stop()


# 애플리케이션 생성: 시작·종료 함수 정의 후 연결
app = FastAPI(
    title=get_settings().app_name,
    lifespan=lifespan,
    description=(
        "날씨 조회, 옷차림 추천과 계정·추천 프로필 관리 API입니다.\n\n"
        "## 공통 응답\n\n"
        "응답 형식: `code`, `message`, `data`, `details`.\n\n"
        "성공 시 code는 SUCCESS이고 data에 결과가 담깁니다. 실패 시 data는 null입니다.\n\n"
        "### 오류 코드 목록\n\n" + error_code_table()
    ),
    openapi_tags=[
        {"name": "weather", "description": "국내 지역 검색과 한국 시간 기준 오늘·7일 예보 조회"},
        {"name": "outfits", "description": "날씨 기반 오늘·7일 옷차림과 추천 이유"},
        {"name": "users", "description": "회원가입·로그인·세션 종료와 본인의 추천 프로필 관리"},
        {"name": "system", "description": "서비스 안내와 서버 응답 상태 확인"},
    ],
)
# 예외 처리기와 업무별 라우터 등록
register_exception_handlers(app)
app.include_router(users_router, prefix="/api/v1")
app.include_router(weather_router, prefix="/api/v1")
app.include_router(outfits_router, prefix="/api/v1")

# 프론트엔드를 빌드해 두면 같은 서버의 /app/에서 화면과 API를 함께 제공한다.
# 개발 서버를 사용할 때나 빌드 전에는 기존 API만 그대로 실행한다.
frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if (frontend_dist / "index.html").is_file():
    # Windows 레지스트리가 .js를 text/plain으로 지정해도 모듈 스크립트로 제공한다.
    mimetypes.add_type("text/javascript", ".js")
    app.mount("/app", StaticFiles(directory=frontend_dist, html=True), name="frontend")


@app.get("/", summary="서비스 기본 안내", description="서비스 안내 메시지를 반환합니다.", tags=["system"], responses=error_responses(include_validation=False))
async def root() -> ApiResponse[dict[str, str]]:
    """서비스 안내 메시지 반환"""
    return ApiResponse(data={"message": "Hello FastAPI"})


@app.get("/health", summary="서버 응답 상태 확인", description="앱의 응답 여부만 확인합니다. DB·외부 API는 검사하지 않습니다.", tags=["system"], responses=error_responses(include_validation=False))
async def health() -> ApiResponse[dict[str, str]]:
    """서버 응답 상태 확인"""
    return ApiResponse(data={"status": "ok"})
