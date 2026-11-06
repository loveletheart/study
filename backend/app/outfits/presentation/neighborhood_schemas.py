"""시군구 공통 추천과 동적 개인화의 독립 생성 정보."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.outfits.application.dto import NeighborhoodResult
from app.outfits.domain.preferences import Activity, ColdSensitivity, OutfitStyle
from app.outfits.presentation.schemas import RecommendationEngineResponse, TodayOutfitResponse, WeeklyOutfitResponse
from app.weather.presentation.schemas import LocationResponse


class PersonalizationResponse(BaseModel):
    cold_sensitivity: ColdSensitivity = Field(description="체감 추위: 보통·추위를 많이 탐·더위를 많이 탐")
    style: OutfitStyle = Field(description="기본·편안한 스타일·단정한 스타일")
    activity: Activity = Field(description="일상·야외·활동량이 많음")
    llm_used: bool = Field(description="개인화 결과가 모델로 생성됐는지 여부. 이번 요청의 캐시 사용은 cache_hit 참조")
    cache_hit: bool = Field(description="개인화 결과를 이번 요청에서 재사용했는지 여부")
    generated_at: datetime | None = Field(description="개인 맞춤 결과 생성 시각. 기본 추천을 그대로 사용하면 null")
    version: str | None = Field(description="개인 맞춤 생성 버전")
    engine: RecommendationEngineResponse | None = Field(description="개인화 결과를 실제 생성한 제공사·모델·프롬프트 버전")
    adjustments: list[str] = Field(description="날씨와 개인 조건을 반영해 모델이 생성한 설명")

    model_config = ConfigDict(from_attributes=True)


class SigunguResponse(BaseModel):
    code: str = Field(pattern=r"^[0-9]{5}$", description="브이월드 시군구 경계 데이터의 sig_cd")
    name: str = Field(description="공식 시군구 이름")
    latitude: float = Field(description="시군구 안에 있다고 최초 확인한 공통 대표점 위도")
    longitude: float = Field(description="고정 대표점 경도. 개인의 정확한 위치와 다를 수 있음")
    source: str = Field(description="행정경계 데이터 출처")
    model_config = ConfigDict(from_attributes=True)


def _personal_metadata(result: NeighborhoodResult) -> dict:
    """공통 생성 정보와 별개로 요청별 적용 조건 표시"""
    return {
        "location": LocationResponse.model_validate(result.location),
        "region": SigunguResponse.model_validate(result.region),
        "personalization": PersonalizationResponse(
            cold_sensitivity=result.preferences.cold_sensitivity,
            style=result.preferences.style, activity=result.preferences.activity,
            adjustments=list(result.adjustments),
            llm_used=result.personalization is not None, cache_hit=result.personalization_cache_hit,
            generated_at=result.personalization.generated_at if result.personalization else None,
            version=result.personalization.version if result.personalization else None,
            engine=RecommendationEngineResponse.model_validate(result.personalization.generated.engine) if result.personalization else None,
        ),
    }


class NeighborhoodTodayResponse(TodayOutfitResponse):
    region: SigunguResponse = Field(description="캐시 공유 기준인 공식 시군구와 대표 위치")
    location: LocationResponse = Field(description="선택한 지역 식별자와 예보 대표 위치. 개인 GPS 위치가 아님")
    personalization: PersonalizationResponse = Field(description="공통 저장값과 분리해 적용한 개인 조건")

    @classmethod
    def from_neighborhood(cls, result: NeighborhoodResult) -> "NeighborhoodTodayResponse":
        """개인화된 오늘 결과와 공유 지역 정보 직렬화"""
        return cls.model_validate({**TodayOutfitResponse.from_result(result.result).model_dump(), **_personal_metadata(result)})


class NeighborhoodWeeklyResponse(WeeklyOutfitResponse):
    region: SigunguResponse = Field(description="주간 추천을 공유하는 공식 시군구")
    location: LocationResponse = Field(description="선택한 지역 식별자와 예보 대표 위치")
    personalization: PersonalizationResponse = Field(description="주간 추천에 적용한 개인 조건")

    @classmethod
    def from_neighborhood(cls, result: NeighborhoodResult) -> "NeighborhoodWeeklyResponse":
        """개인화된 주간 결과와 공유 지역 정보 직렬화"""
        return cls.model_validate({**WeeklyOutfitResponse.from_result(result.result).model_dump(), **_personal_metadata(result)})
