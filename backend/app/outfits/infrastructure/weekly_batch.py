"""주간 추천은 오늘의 시간별 확인 작업과 분리한 일일 배치로 실행한다."""

from app.outfits.infrastructure.personalized_cache import SQLitePersonalizedOutfitCache
from app.outfits.infrastructure.result_cache import CachedOutfitService


class WeeklyOutfitBatch:
    def __init__(self, common: CachedOutfitService, personalized: SQLitePersonalizedOutfitCache) -> None:
        """주간 기본 결과를 준비한 뒤 해당 지역의 개인 결과도 준비"""
        self._common = common
        self._personalized = personalized

    def refresh_due(self, stopped=None) -> dict:
        """서버의 분 단위 확인에서 한국 시간 새벽 배치만 시작"""
        return self._common.run_weekly_batch(stopped=stopped, on_ready=self._personalized.prepare_weekly)
