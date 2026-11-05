from datetime import date as Date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.outfits.application.dto import OutfitForecast, TodayOutfitResult, WeeklyOutfitResult
from app.outfits.domain.models import TemperatureBasis


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
    top: str = Field(description="상의 구성")
    bottom: str = Field(description="하의 구성")
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


class RecommendationEngineResponse(AttributeResponse):
    provider: str = Field(description="옷차림 생성 제공사. ollama 또는 gemini")
    model: str = Field(description="추천에 실제 사용한 모델명")
    prompt_version: str = Field(description="추천 프롬프트 버전")
    fallback_used: bool = Field(description="로컬 실패 후 클라우드로 자동 전환했는지 여부")
    fallback_reason: str | None = Field(description="전환 원인이 된 공통 오류 코드. 전환하지 않으면 null")


class OutfitMetadataResponse(AttributeResponse):
    coordinates: OutfitCoordinatesResponse = Field(description="요청한 위치의 위도·경도")
    timezone: str = Field(description="예보와 추천 날짜의 시간대. Asia/Seoul")
    fetched_at: datetime = Field(description="서버가 날씨 데이터를 가져온 시각. 캐시 재사용 시 최초 조회 시각")
    provider: str = Field(description="날씨 데이터 제공사")
    source_url: str = Field(description="화면에 표시할 날씨 데이터 출처 링크")
    engine: RecommendationEngineResponse = Field(description="실제 옷차림을 생성한 LLM 정보")
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
        return cls.model_validate({**_metadata(result.forecast), "engine": result.engine, "recommendation": result.recommendation})


class WeeklyOutfitResponse(OutfitMetadataResponse):
    daily: list[OutfitRecommendationResponse] = Field(min_length=7, max_length=7, description="오늘부터 날짜순으로 정렬한 7일 추천")
    wardrobe: WeeklyWardrobeResponse = Field(description="날짜별 베스트 옷차림을 합친 주간 준비 의류")
    summary: str = Field(description="7일 예상 기온과 준비 안내")

    @classmethod
    def from_result(cls, result: WeeklyOutfitResult) -> "WeeklyOutfitResponse":
        """주간 추천 결과를 응답으로 변환"""
        return cls.model_validate({
            **_metadata(result.forecast), "daily": result.daily,
            "wardrobe": result.wardrobe, "summary": result.summary, "engine": result.engine,
        })
