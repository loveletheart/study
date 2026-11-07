"""로컬 우선과 허용된 실패의 클라우드 전환 정책."""

import logging
from collections.abc import Callable
from dataclasses import replace
from app.outfits.application.dto import GeneratedOutfits
from app.outfits.application.exceptions import OutfitLlmModelNotFoundError, OutfitLlmNotConfiguredError, OutfitLlmResponseError, OutfitLlmTimeoutError, OutfitLlmUnavailableError
from app.outfits.application.ports import OutfitRecommender
from app.outfits.domain.models import OutfitWeather


logger = logging.getLogger(__name__)


FALLBACK_ERRORS = (
    OutfitLlmNotConfiguredError, OutfitLlmModelNotFoundError, OutfitLlmUnavailableError,
    OutfitLlmTimeoutError, OutfitLlmResponseError,
)


class FallbackOutfitRecommender:
    def __init__(
        self, local: Callable[[], OutfitRecommender], cloud: Callable[[], OutfitRecommender],
    ) -> None:
        """필요할 때 생성할 로컬·클라우드 추천 구현 연결"""
        self._local = local
        self._cloud = cloud

    def recommend(self, days: tuple[OutfitWeather, ...]) -> GeneratedOutfits:
        """로컬을 우선하고 허용된 오류에만 클라우드 한 번 호출"""
        try:
            return self._local().recommend(days)
        except FALLBACK_ERRORS as exc:
            reason = exc.error_code.value
            logger.warning("로컬 옷차림 LLM 실패(%s): Gemini 자동 전환 시도", reason)
        generated = self._cloud().recommend(days)
        return replace(generated, engine=replace(generated.engine, fallback_used=True, fallback_reason=reason))
