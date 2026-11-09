"""기본·지역·개인화 옷차림 API의 응답 모델."""

# 표준 라이브러리
from datetime import date as Date, datetime

# 외부 라이브러리
from pydantic import BaseModel, ConfigDict, Field

# 프로젝트 모듈
from app.outfits.application.dto import (
    OutfitForecast,
    TodayOutfitResult,
    WeeklyOutfitResult,
    RegionOutfitResult,
)
from app.outfits.domain.models import OutfitType, TemperatureBasis, Activity, ColdSensitivity, OutfitStyle, ClothingPreference, AvoidItem
from app.weather.presentation.schemas import LocationResponse


class AttributeResponse(BaseModel):
    """DTO와 도메인 객체의 속성을 읽는 응답 모델."""

    model_config = ConfigDict(from_attributes=True)


class OutfitCoordinatesResponse(AttributeResponse):
    latitude: float = Field(description="조회한 위도")
    longitude: float = Field(description="조회한 경도")


class OutfitWeatherResponse(AttributeResponse):
    date: Date = Field(description="예보 날짜(Asia/Seoul)")
    temperature_min_c: float = Field(description="일 최저기온(°C)")
    temperature_max_c: float = Field(description="일 최고기온(°C)")
    apparent_temperature_min_c: float | None = Field(description="일 최저 체감온도(°C). 미제공 시 null")
    apparent_temperature_max_c: float | None = Field(description="일 최고 체감온도(°C). 미제공 시 null")
    precipitation_probability_percent: float | None = Field(description="하루 중 최대 강수확률(%). 미제공 시 null")
    precipitation_mm: float | None = Field(description="하루 누적 강수량(mm). 미제공 시 null")
    snowfall_cm: float | None = Field(description="하루 누적 적설량(cm). 미제공 시 null")
    wind_speed_m_s: float | None = Field(description="하루 최대 풍속(m/s). 미제공 시 null")
    uv_index: float | None = Field(description="하루 최대 자외선 지수. 미제공 시 null")
    weather_code: int = Field(description="그날의 대표 WMO 날씨 코드")
    description: str = Field(description="날씨 서비스가 제공한 코드의 한글 설명")


class OutfitLookResponse(AttributeResponse):
    outfit_type: OutfitType = Field(description="separates는 상하의 조합, one_piece는 원피스·점프수트")
    top: str | None = Field(description="상의 구성. 원피스 구성이면 null")
    bottom: str | None = Field(description="하의 구성. 원피스 구성이면 null")
    one_piece: str | None = Field(description="원피스·점프수트 구성. 상하의 조합이면 null")
    outerwear: str | None = Field(description="겉옷 구성. 필요 없으면 null")
    shoes: str = Field(description="신발 구성")
    accessories: list[str] = Field(description="장갑·우산 등 추가 준비물")


class OutfitRecommendationResponse(AttributeResponse):
    date: Date = Field(description="추천 날짜(Asia/Seoul)")
    weather: OutfitWeatherResponse = Field(description="추천 판단에 사용한 일별 예보")
    temperature_basis: TemperatureBasis = Field(description="체감온도 우선. 최저·최고 체감온도 중 하나라도 없으면 실제 기온 사용")
    reference_temperature_c: float = Field(description="모델에 전달한 낮 기준 최고 체감온도 또는 최고기온(°C). 최저 온도와 함께 판단합니다.")
    best: OutfitLookResponse = Field(description="날씨에 맞는 베스트 옷차림")
    worst: OutfitLookResponse = Field(description="그날 피하는 편이 좋은 워스트 옷차림")
    reasons: list[str] = Field(description="베스트 옷차림의 구성 이유")
    avoid_reasons: list[str] = Field(description="워스트 옷차림을 피해야 하는 이유")
    precautions: list[str] = Field(description="시간대별 겉옷 조절, 강수와 누락 정보 등 참고 사항")


class WeeklyWardrobeResponse(AttributeResponse):
    tops: list[str] = Field(description="이번 7일에 필요한 상의 종류. 중복 제외")
    bottoms: list[str] = Field(description="이번 7일에 필요한 하의 종류. 중복 제외")
    outerwear: list[str] = Field(description="이번 7일에 필요한 겉옷 종류. 중복 제외")
    shoes: list[str] = Field(description="이번 7일에 필요한 신발 종류. 중복 제외")
    accessories: list[str] = Field(description="이번 7일에 필요한 추가 준비물. 중복 제외")
    one_pieces: list[str] = Field(default_factory=list, description="이번 7일에 필요한 원피스·점프수트 종류. 중복 제외")


class RecommendationEngineResponse(AttributeResponse):
    generation_id: str | None = Field(default=None, description="서버에 보존한 실제 추천 원본의 식별자")
    provider: str = Field(description="옷차림 생성 제공사. ollama 또는 gemini")
    model: str = Field(description="추천에 실제 사용한 모델명")
    prompt_version: str = Field(description="추천 프롬프트 버전")
    fallback_used: bool = Field(description="로컬 실패 후 클라우드로 자동 전환했는지 여부")
    fallback_reason: str | None = Field(description="전환 원인이 된 공통 오류 코드. 전환하지 않으면 null")


class OutfitMetadataResponse(AttributeResponse):
    coordinates: OutfitCoordinatesResponse = Field(description="요청한 위치의 위도·경도")
    timezone: str = Field(description="예보와 추천 날짜의 시간대. Asia/Seoul")
    fetched_at: datetime = Field(description="추천에 사용한 날씨의 최근 조회 시각. 날씨가 같아 기본 추천을 재사용하면 generated_at과 다를 수 있음")
    generated_at: datetime | None = Field(default=None, description="기본 추천을 실제 생성한 시각. 구버전 저장값이면 null")
    base_version: str | None = Field(default=None, description="공통 추천 생성 버전. 날씨가 같으면 갱신해도 유지")
    provider: str = Field(description="날씨 데이터 제공사")
    source_url: str = Field(description="화면에 표시할 날씨 데이터 출처 링크")
    engine: RecommendationEngineResponse = Field(description="공통 기본 추천을 생성한 LLM 정보. 동네 경로의 개인 맞춤 생성 정보는 personalization.engine 참조")
    notice: str = Field(default="날씨 기반의 일반적인 참고 추천입니다. 개인의 체감과 실제 예보에 맞춰 조절하세요.", description="추천 이용 안내")


def _metadata(forecast: OutfitForecast) -> dict[str, object]:
    """오늘·주간 응답이 공유하는 출처와 위치 추출"""
    return {
        "coordinates": forecast.coordinates, "timezone": forecast.timezone,
        "fetched_at": forecast.fetched_at, "provider": forecast.provider, "source_url": forecast.source_url,
    }


class TodayOutfitResponse(OutfitMetadataResponse):
    recommendation: OutfitRecommendationResponse = Field(description="오늘의 옷차림과 판단 이유")

    @classmethod
    def from_result(cls, result: TodayOutfitResult) -> "TodayOutfitResponse":
        """오늘 추천 결과를 응답으로 변환"""
        return cls.model_validate({
            **_metadata(result.forecast), "engine": result.engine, "recommendation": result.recommendation,
            "generated_at": result.generated_at, "base_version": result.base_version,
        })


class WeeklyOutfitResponse(OutfitMetadataResponse):
    forecast_start_date: Date = Field(description="최근 주간 배치가 사용한 예보의 첫 날짜. 현재 날짜와 다를 수 있음")
    daily: list[OutfitRecommendationResponse] = Field(min_length=7, max_length=7, description="forecast_start_date부터 날짜순으로 정렬한 7일 추천")
    notice: str = Field(default="최근 야간 배치 기준 7일 추천입니다. 생성 시각·예보 날짜를 확인하고 외출 전 최신 날씨를 참고하세요.")
    wardrobe: WeeklyWardrobeResponse = Field(description="날짜별 베스트 옷차림을 합친 주간 준비 의류")
    summary: str = Field(description="7일 예상 기온과 준비 안내")

    @classmethod
    def from_result(cls, result: WeeklyOutfitResult) -> "WeeklyOutfitResponse":
        """주간 추천 결과를 응답으로 변환"""
        return cls.model_validate({
            **_metadata(result.forecast), "daily": result.daily,
            "wardrobe": result.wardrobe, "summary": result.summary, "engine": result.engine,
            "generated_at": result.generated_at, "base_version": result.base_version,
            "forecast_start_date": result.forecast.today,
        })


class PersonalizationResponse(BaseModel):
    clothing_preference: ClothingPreference = Field(default=ClothingPreference.ANY, description="선호 의류 유형")
    avoid_items: list[AvoidItem] = Field(default_factory=list, description="피하고 싶은 의류")
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


def _personal_metadata(result: RegionOutfitResult[TodayOutfitResult] | RegionOutfitResult[WeeklyOutfitResult]) -> dict:
    """공통 생성 정보와 별개로 요청별 적용 조건 표시"""
    return {
        "location": LocationResponse.model_validate(result.location),
        "region": SigunguResponse.model_validate(result.region),
        "personalization": PersonalizationResponse(
            cold_sensitivity=result.preferences.cold_sensitivity,
            style=result.preferences.style, activity=result.preferences.activity,
            clothing_preference=result.preferences.clothing_preference, avoid_items=list(result.preferences.avoid_items),
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
    def from_region(cls, result: RegionOutfitResult[TodayOutfitResult]) -> "NeighborhoodTodayResponse":
        """개인화된 오늘 결과와 공유 지역 정보 직렬화"""
        return cls.model_validate({**TodayOutfitResponse.from_result(result.result).model_dump(), **_personal_metadata(result)})


class NeighborhoodWeeklyResponse(WeeklyOutfitResponse):
    region: SigunguResponse = Field(description="주간 추천을 공유하는 공식 시군구")
    location: LocationResponse = Field(description="선택한 지역 식별자와 예보 대표 위치")
    personalization: PersonalizationResponse = Field(description="주간 추천에 적용한 개인 조건")

    @classmethod
    def from_region(cls, result: RegionOutfitResult[WeeklyOutfitResult]) -> "NeighborhoodWeeklyResponse":
        """개인화된 주간 결과와 공유 지역 정보 직렬화"""
        return cls.model_validate({**WeeklyOutfitResponse.from_result(result.result).model_dump(), **_personal_metadata(result)})
