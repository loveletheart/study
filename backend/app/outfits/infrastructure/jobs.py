"""공통·개인 갱신 실행기와 주간 배치를 함께 관리한다."""

import logging
from threading import Event, Thread
from typing import Protocol
from app.outfits.infrastructure.cache import SQLitePersonalizedOutfitCache, CachedOutfitService


logger = logging.getLogger(__name__)


class RefreshTask(Protocol):
    def refresh_due(self, stopped: Event | None = None) -> object:
        """갱신 작업이 제공해야 하는 실행 계약."""
        ...


class OutfitRefreshWorker:
    def __init__(self, service: RefreshTask) -> None:
        """서버 수명 동안 실행할 단일 갱신 작업 준비"""
        self._service = service
        self._stopped = Event()
        self._thread = Thread(target=self._run, name="outfit-refresh", daemon=True)

    def start(self) -> None:
        """서버 시작을 막지 않고 저장된 지역의 갱신 시작"""
        self._thread.start()

    def stop(self) -> None:
        """추가 갱신을 중단하고 진행 중인 외부 요청은 기존 제한 시간 적용"""
        self._stopped.set()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        """분마다 갱신 기한을 확인하고 긴 생성 작업은 겹치지 않게 실행"""
        while not self._stopped.is_set():
            try:
                self._service.refresh_due(self._stopped)
            except Exception as exc:
                logger.warning("옷차림 갱신 작업 실패: cause=%s", type(exc).__name__)
            self._stopped.wait(60)


class WeeklyOutfitBatch:
    def __init__(self, common: CachedOutfitService, personalized: SQLitePersonalizedOutfitCache) -> None:
        """주간 기본 결과를 준비한 뒤 해당 지역의 개인 결과도 준비"""
        self._common = common
        self._personalized = personalized

    def refresh_due(self, stopped=None) -> dict:
        """서버의 분 단위 확인에서 한국 시간 새벽 배치만 시작"""
        return self._common.run_weekly_batch(stopped=stopped, on_ready=self._personalized.prepare_weekly)
