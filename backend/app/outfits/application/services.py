from datetime import timedelta

from app.outfits.application.dto import OutfitForecast, TodayOutfitResult, WeeklyOutfitResult
from app.outfits.application.exceptions import OutfitForecastError
from app.outfits.application.ports import OutfitWeatherReader
from app.outfits.domain.rules import build_weekly_wardrobe, recommend_outfit


class OutfitService:
    def __init__(self, weather: OutfitWeatherReader) -> None:
        """옷차림용 날씨 조회 구현 주입"""
        self._weather = weather

    def get_today(self, latitude: float, longitude: float) -> TodayOutfitResult:
        """오늘의 추천·비추천 옷차림 구성"""
        forecast = self._get_forecast(latitude, longitude)
        return TodayOutfitResult(forecast, recommend_outfit(forecast.days[0]))

    def get_weekly(self, latitude: float, longitude: float) -> WeeklyOutfitResult:
        """7일 옷차림과 공통 준비 의류 구성"""
        forecast = self._get_forecast(latitude, longitude)
        daily = tuple(recommend_outfit(day) for day in forecast.days)
        minimum = min(day.temperature_min_c for day in forecast.days)
        maximum = max(day.temperature_max_c for day in forecast.days)
        summary = f"이번 7일간 최저 {minimum:g}℃, 최고 {maximum:g}℃가 예상됩니다. 날짜별 옷차림과 공통 준비물을 확인하세요."
        return WeeklyOutfitResult(forecast, daily, build_weekly_wardrobe(daily), summary)

    def _get_forecast(self, latitude: float, longitude: float) -> OutfitForecast:
        """오늘부터 연속된 7일 예보인지 확인"""
        forecast = self._weather.get_forecast(latitude, longitude)
        expected = tuple(forecast.today + timedelta(days=index) for index in range(7))
        if forecast.timezone != "Asia/Seoul" or tuple(day.date for day in forecast.days) != expected:
            raise OutfitForecastError()
        return forecast
