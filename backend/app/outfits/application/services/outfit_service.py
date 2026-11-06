"""날씨 검증과 공통 옷차림 추천의 응용 서비스."""

from datetime import datetime, timedelta
from dataclasses import replace
from uuid import uuid4

from app.outfits.application.dto import GeneratedOutfits, OutfitForecast, TodayOutfitResult, WeeklyOutfitResult
from app.outfits.application.exceptions import OutfitForecastError, OutfitLlmResponseError
from app.outfits.application.ports import OutfitRecommender, OutfitWeatherReader
from app.outfits.domain.models import OutfitWeather
from app.outfits.domain.rules import build_weekly_wardrobe, temperature_reference
from app.weather.domain.models import KST


class OutfitService:
    def __init__(self, weather: OutfitWeatherReader, recommender: OutfitRecommender) -> None:
        """날씨 조회와 옷차림 생성 구현 주입"""
        self._weather = weather
        self._recommender = recommender

    def get_today(self, latitude: float, longitude: float) -> TodayOutfitResult:
        """오늘의 추천·비추천 옷차림 구성"""
        forecast = self._get_forecast(latitude, longitude)
        return self._today(forecast)

    def _today(self, forecast: OutfitForecast) -> TodayOutfitResult:
        """검증한 오늘 예보로 새 기본 추천 생성"""
        generated = self._recommend(forecast.days[:1])
        return TodayOutfitResult(
            forecast, generated.recommendations[0], generated.engine, datetime.now(KST), uuid4().hex,
        )

    def get_weekly(self, latitude: float, longitude: float) -> WeeklyOutfitResult:
        """7일 옷차림과 공통 준비 의류 구성"""
        forecast = self._get_forecast(latitude, longitude)
        return self._weekly(forecast)

    def _weekly(self, forecast: OutfitForecast) -> WeeklyOutfitResult:
        """검증한 주간 예보로 새 기본 추천 생성"""
        generated = self._recommend(forecast.days)
        daily = generated.recommendations
        minimum = min(day.temperature_min_c for day in forecast.days)
        maximum = max(day.temperature_max_c for day in forecast.days)
        summary = f"이번 7일간 최저 {minimum:g}℃, 최고 {maximum:g}℃가 예상됩니다. 날짜별 옷차림과 공통 준비물을 확인하세요."
        return WeeklyOutfitResult(
            forecast, daily, build_weekly_wardrobe(daily), summary, generated.engine, datetime.now(KST), uuid4().hex,
        )

    def refresh_today(self, latitude: float, longitude: float, previous: TodayOutfitResult) -> TodayOutfitResult:
        """오늘 판단에 사용하는 날씨가 같으면 기존 추천과 생성 버전 유지"""
        forecast = self._get_forecast(latitude, longitude)
        if forecast.days[:1] == previous.forecast.days[:1]:
            return replace(previous, forecast=forecast)
        return self._today(forecast)

    def refresh_weekly(self, latitude: float, longitude: float, previous: WeeklyOutfitResult) -> WeeklyOutfitResult:
        """주간 판단에 사용하는 날씨가 같으면 모델을 다시 호출하지 않음"""
        forecast = self._get_forecast(latitude, longitude)
        if forecast.days == previous.forecast.days:
            return replace(previous, forecast=forecast)
        return self._weekly(forecast)

    def _recommend(self, days: tuple[OutfitWeather, ...]) -> GeneratedOutfits:
        """생성 결과의 날짜·온도·날씨가 원본과 일치하는지 확인"""
        generated = self._recommender.recommend(days)
        if len(generated.recommendations) != len(days):
            raise OutfitLlmResponseError()
        for weather, recommendation in zip(days, generated.recommendations):
            basis, reference = temperature_reference(weather)
            if (
                recommendation.date != weather.date or recommendation.weather != weather
                or recommendation.temperature_basis != basis or recommendation.reference_temperature_c != reference
            ):
                raise OutfitLlmResponseError()
        return generated

    def _get_forecast(self, latitude: float, longitude: float) -> OutfitForecast:
        """오늘부터 연속된 7일 예보인지 확인"""
        forecast = self._weather.get_forecast(latitude, longitude)
        expected = tuple(forecast.today + timedelta(days=index) for index in range(7))
        if forecast.timezone != "Asia/Seoul" or tuple(day.date for day in forecast.days) != expected:
            raise OutfitForecastError()
        return forecast
