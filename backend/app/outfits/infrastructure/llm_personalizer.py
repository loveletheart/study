"""공통 추천의 원본 날씨와 개인 조건으로 의류·설명을 새로 생성한다."""

import json
from collections.abc import Callable
from dataclasses import asdict, replace

from app.outfits.application.dto import GeneratedOutfits
from app.outfits.application.ports import OutfitRecommender
from app.outfits.domain.preferences import Activity, ColdSensitivity, OutfitPreferences, OutfitStyle
from app.outfits.infrastructure.structured_recommender import StructuredChatClient

PERSONALIZATION_VERSION = "2.3"
PERSONALIZATION_INSTRUCTION = """Apply all explicit preferences and personal_requirements together.
cold_sensitivity='cold' means feels cold easily; 'warm' means feels hot easily; normal means neither. Never reverse them.
formal requires a neat formal outfit; casual prioritizes everyday comfort; active needs movement and sweat management; outdoor requires protection from exposure.
Explain how the actual selected clothes fit this person's needs and weather. Avoid stock phrases.
Heat sensitivity never removes necessary cold protection; cold sensitivity never justifies winter clothes in heat."""


def _personal_requirements(preferences: OutfitPreferences) -> dict[str, str]:
    """선택값의 의미를 모델에 설명하며 사용자에게 보여줄 추천 문장은 만들지 않는다."""
    return {
        "체온_성향": {
            ColdSensitivity.NORMAL: "추위와 더위에 대한 민감도는 보통입니다. 하루의 기온 범위에 맞춰 조절하세요.",
            ColdSensitivity.COLD: "추위를 많이 탑니다. 추운 시간과 야외 활동의 보온·방풍, 노출 감소를 우선 고려하세요.",
            ColdSensitivity.WARM: "더위를 많이 탑니다. 통풍·흡습과 쉽게 벗는 레이어를 고려하되 추운 시간의 방한은 유지하세요.",
        }[preferences.cold_sensitivity],
        "스타일": {
            OutfitStyle.DEFAULT: "특정 스타일을 요구하지 않았습니다. 명시된 날씨와 활동에 맞는 일상복을 구성하세요.",
            OutfitStyle.CASUAL: "편안한 캐주얼 스타일을 원합니다. 움직임이 편하고 일상에서 조화로운 구성을 선택하세요.",
            OutfitStyle.FORMAL: "격식 있고 단정한 스타일을 원합니다. 스포츠웨어 중심의 조합을 피하고 소재와 실루엣을 고려하세요.",
        }[preferences.style],
        "활동": {
            Activity.DAILY: "일상 활동을 할 예정입니다. 특정 직업이나 별도의 운동 계획은 가정하지 마세요.",
            Activity.OUTDOOR: "야외 활동을 할 예정입니다. 외기에 노출되므로 최저 기온·강수·바람과 활동 편의성을 고려하세요.",
            Activity.ACTIVE: "몸을 활발히 움직이는 활동을 할 예정입니다. 신축성·흡습·통풍과 활동 전후 체온 조절을 고려하세요.",
        }[preferences.activity],
    }


class PersonalizationChatClient:
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
    def __init__(self, factory: Callable[[GeneratedOutfits, OutfitPreferences], OutfitRecommender]) -> None:
        """지역 공통 추천과 동일한 통신·검증·전환 정책 사용"""
        self._factory = factory

    def personalize(self, base: GeneratedOutfits, preferences: OutfitPreferences) -> GeneratedOutfits:
        """동적 생성 결과에 개인화 프롬프트 버전과 실제 제공사 기록"""
        days = tuple(item.weather for item in base.recommendations)
        generated = self._factory(base, preferences).recommend(days)
        return replace(generated, engine=replace(generated.engine, prompt_version=PERSONALIZATION_VERSION))
