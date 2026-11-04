from pydantic import ValidationError

from app.outfits.application.dto import GeneratedOutfits, RecommendationEngine
from app.outfits.application.exceptions import OutfitLlmNotConfiguredError, OutfitLlmResponseError
from app.outfits.domain.models import OutfitLook, OutfitRecommendation, OutfitWeather, TemperatureBasis
from app.outfits.domain.rules import temperature_reference
from app.outfits.infrastructure.llm_schemas import GeneratedLook, GeneratedResponse
from app.outfits.infrastructure.ollama_client import OllamaClient
from app.outfits.infrastructure.prompts import PROMPT_VERSION, build_messages


def _look(value: GeneratedLook) -> OutfitLook:
    """검증한 모델의 의류 구성을 도메인 객체로 변환"""
    return OutfitLook(value.top, value.bottom, value.outerwear, value.shoes, tuple(dict.fromkeys(value.accessories)))


class OllamaOutfitRecommender:
    def __init__(self, client: OllamaClient, model: str) -> None:
        """로컬 추론 클라이언트와 모델 지정"""
        if not model.strip():
            raise OutfitLlmNotConfiguredError()
        self._client = client
        self._model = model.strip()

    def recommend(self, days: tuple[OutfitWeather, ...]) -> GeneratedOutfits:
        """날씨를 한 번에 전달하고 생성 결과의 날짜·내용 검증"""
        if not 1 <= len(days) <= 7:
            raise OutfitLlmResponseError()
        schema = GeneratedResponse.model_json_schema()
        schema["properties"]["days"].update(minItems=len(days), maxItems=len(days))
        schema["$defs"]["GeneratedDay"]["properties"]["date"]["enum"] = [day.date.isoformat() for day in days]
        content = self._client.chat(self._model, build_messages(days, schema), schema)
        try:
            generated = GeneratedResponse.model_validate_json(content, strict=True)
        except ValidationError as exc:
            raise OutfitLlmResponseError() from exc
        if tuple(day.date for day in generated.days) != tuple(day.date for day in days):
            raise OutfitLlmResponseError()
        recommendations = []
        for weather, day in zip(days, generated.days):
            best, worst = _look(day.best), _look(day.worst)
            if (
                (best.top, best.bottom, best.outerwear, best.shoes) == (worst.top, worst.bottom, worst.outerwear, worst.shoes)
                and set(best.accessories) == set(worst.accessories)
            ):
                raise OutfitLlmResponseError()
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
        return GeneratedOutfits(
            tuple(recommendations), RecommendationEngine("ollama", self._model, PROMPT_VERSION),
        )
