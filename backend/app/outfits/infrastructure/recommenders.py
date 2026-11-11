"""공통 생성 검증·제공사별 생성기·개인화를 한곳에서 관리한다."""

# 표준 라이브러리
from typing import Protocol
import json
from collections.abc import Callable
from dataclasses import asdict, replace

# 외부 라이브러리
from pydantic import ValidationError

# 프로젝트 모듈
from app.common.errors.exceptions import AppError
from app.outfits.application.dto import GeneratedOutfits, RecommendationEngine
from app.outfits.application.exceptions import (
    OutfitLlmNotConfiguredError,
    OutfitLlmResponseError,
    OutfitLlmTimeoutError,
    OutfitCloudNotConfiguredError,
    OutfitCloudResponseError,
)
from app.outfits.domain.models import (
    OutfitLook,
    OutfitRecommendation,
    OutfitWeather,
    TemperatureBasis,
    OutfitPreferences,
)
from app.outfits.domain.rules import temperature_reference
from app.outfits.infrastructure.schemas import GeneratedLook, GeneratedResponse
from app.outfits.infrastructure.prompts import (
    PROMPT_VERSION,
    build_messages,
    PERSONALIZATION_VERSION,
    PERSONALIZATION_INSTRUCTION,
    _personal_requirements,
)
from app.outfits.application.ports import OutfitRecommender
from app.outfits.domain.quality import check_day


def _look(value: GeneratedLook) -> OutfitLook:
    """검증한 모델의 의류 구성을 도메인 객체로 변환"""
    return OutfitLook(
        value.top, value.bottom, value.outerwear, value.shoes, tuple(dict.fromkeys(value.accessories)),
        outfit_type=value.outfit_type, one_piece=value.one_piece,
    )


class StructuredChatClient(Protocol):
    def chat(self, model: str, messages: list[dict[str, str]], schema: dict) -> str:
        """메시지와 출력 스키마에 맞는 JSON 생성"""
        ...


class StructuredOutfitRecommender:
    def __init__(
        self, client: StructuredChatClient, model: str, provider: str,
        response_error: type[AppError] = OutfitLlmResponseError,
        configuration_error: type[AppError] = OutfitLlmNotConfiguredError,
        *, repair_attempts: int = 0, retry_on_timeout: bool = False,
    ) -> None:
        """추론 클라이언트와 제공사별 오류 설정"""
        if not model.strip():
            raise configuration_error()
        self._client = client
        self._model = model.strip()
        self._provider = provider
        self._response_error = response_error
        self._repair_attempts = min(max(repair_attempts, 0), 1)
        self._retry_on_timeout = retry_on_timeout

    def _generate(self, days: tuple[OutfitWeather, ...], schema: dict) -> GeneratedResponse:
        """검증 실패와 허용된 시간 초과가 같은 재시도 횟수를 사용한다."""
        messages = build_messages(days, schema)
        for attempt in range(self._repair_attempts + 1):
            last_attempt = attempt == self._repair_attempts
            try:
                content = self._client.chat(self._model, messages, schema)
            except OutfitLlmTimeoutError:
                if last_attempt or not self._retry_on_timeout:
                    raise
                continue
            try:
                generated = GeneratedResponse.model_validate_json(content, strict=True)
                if tuple(day.date for day in generated.days) != tuple(day.date for day in days):
                    raise ValueError('요청한 날짜와 순서를 지켜 주세요.')
                errors = [issue for result, weather in zip(generated.days, days)
                          for issue in check_day(result.model_dump(mode='json'), asdict(weather))['errors']]
                if errors:
                    raise ValueError(' '.join(dict.fromkeys(issue['message'] for issue in errors)))
                return generated
            except (ValidationError, ValueError) as error:
                if last_attempt:
                    raise self._response_error() from error
                payload = json.loads(messages[1]['content'])
                payload['answer_checks'] = [
                    '출력 스키마의 의류 구성과 필드·개수 제한을 확인해 주세요.' if isinstance(error, ValidationError) else str(error)[:500],
                    '위 문제를 수정한 최종 추천만 JSON으로 반환하세요. 검사 지시문 자체를 추천 이유에 쓰지 마세요.',
                ]
                messages[1] = {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, allow_nan=False)}
        raise self._response_error()

    def recommend(self, days: tuple[OutfitWeather, ...]) -> GeneratedOutfits:
        """날씨를 한 번에 전달하고 생성 결과의 날짜·내용 검증"""
        if not 1 <= len(days) <= 7:
            raise self._response_error()
        schema = GeneratedResponse.model_json_schema()
        schema["properties"]["days"].update(minItems=len(days), maxItems=len(days))
        schema["$defs"]["GeneratedDay"]["properties"]["date"]["enum"] = [day.date.isoformat() for day in days]
        generated = self._generate(days, schema)
        if (
            generated is None or not hasattr(generated, 'days')
            or generated.days is None or not generated.days
        ):
            raise self._response_error()

        recommendations = []

        for weather, day in zip(days, generated.days):
            best, worst = _look(day.best), _look(day.worst)
            if (
                (best.outfit_type, best.top, best.bottom, best.one_piece, best.outerwear, best.shoes)
                == (worst.outfit_type, worst.top, worst.bottom, worst.one_piece, worst.outerwear, worst.shoes)
                and set(best.accessories) == set(worst.accessories)
            ):
                raise self._response_error()
            basis, reference = temperature_reference(weather)
            reasons = list(day.reasons)
            precautions = list(day.precautions)
            if basis is TemperatureBasis.ACTUAL:
                reasons.append("최저·최고 체감온도가 모두 제공되지 않아 실제 기온을 기준으로 사용했습니다.")
            if weather.precipitation_probability_percent is None:
                precautions.append("강수확률 정보가 제공되지 않았습니다.")
            if weather.wind_speed_m_s is None:
                precautions.append("풍속 정보가 제공되지 않았습니다.")
            recommendations.append(OutfitRecommendation(
                date=weather.date, weather=weather, temperature_basis=basis, reference_temperature_c=reference,
                best=best, worst=worst, reasons=tuple(dict.fromkeys(reasons)),
                avoid_reasons=tuple(dict.fromkeys(day.avoid_reasons)), precautions=tuple(dict.fromkeys(precautions)),
            ))
        generation_id = getattr(self._client, 'last_generation_id', None)
        return GeneratedOutfits(
            tuple(recommendations), RecommendationEngine(self._provider, self._model, PROMPT_VERSION, generation_id=generation_id if isinstance(generation_id, str) else None),
        )


class OllamaOutfitRecommender(StructuredOutfitRecommender):
    def __init__(
        self, client: StructuredChatClient, model: str,
        *, repair_attempts: int = 0, retry_on_timeout: bool = False,
    ) -> None:
        """Ollama 응답에 공통 추천 검증 적용"""
        super().__init__(
            client, model, "ollama", repair_attempts=repair_attempts, retry_on_timeout=retry_on_timeout,
        )


class GeminiOutfitRecommender(StructuredOutfitRecommender):
    def __init__(self, client: StructuredChatClient, model: str) -> None:
        """Gemini 응답에 공통 옷차림 검증과 클라우드 오류 처리를 적용한다."""
        super().__init__(client, model, "gemini", OutfitCloudResponseError, OutfitCloudNotConfiguredError)


class PersonalizationChatClient:
    @property
    def last_generation_id(self):
        return getattr(self._client, 'last_generation_id', None)

    def __init__(self, client: StructuredChatClient, preferences: OutfitPreferences) -> None:
        """날씨 검증용 클라이언트에 개인화 문맥을 추가한다."""
        self._client = client
        self._preferences = preferences

    def chat(self, model: str, messages: list[dict[str, str]], schema: dict) -> str:
        """응답 문구를 코드에서 합성하지 않고 모델의 검증 대상 JSON으로 받는다."""
        content = json.loads(messages[1]["content"])
        content["preferences"] = asdict(self._preferences)
        content["personal_requirements"] = _personal_requirements(self._preferences)
        contextual = [
            {"role": "system", "content": messages[0]["content"] + "\n" + PERSONALIZATION_INSTRUCTION},
            {"role": "user", "content": json.dumps(content, ensure_ascii=False, allow_nan=False, default=str)},
        ]
        return self._client.chat(model, contextual, schema)


class LlmOutfitPersonalizer:
    def __init__(self, factory: Callable[[OutfitPreferences], OutfitRecommender]) -> None:
        """지역 공통 추천과 동일한 통신·검증·전환 정책 사용"""
        self._factory = factory

    def personalize(self, base: GeneratedOutfits, preferences: OutfitPreferences) -> GeneratedOutfits:
        """동적 생성 결과에 개인화 프롬프트 버전과 실제 제공사 기록"""
        days = tuple(item.weather for item in base.recommendations)
        generated = self._factory(preferences).recommend(days)
        return replace(generated, engine=replace(generated.engine, prompt_version=PERSONALIZATION_VERSION))
