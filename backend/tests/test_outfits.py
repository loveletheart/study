"""외부 통신 없이 옷차림 규칙·날씨 연결·응답 계약 검증."""

import copy
import json
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from unittest.mock import Mock

from fastapi import Request
from pydantic import TypeAdapter, ValidationError

from app.common.errors.handlers import handle_app_error
from app.outfits.application.exceptions import OutfitForecastError
from app.outfits.application.services import OutfitService
from app.outfits.domain.models import OutfitWeather, TemperatureBasis
from app.outfits.domain.rules import build_weekly_wardrobe, recommend_outfit
from app.outfits.infrastructure.weather_reader import WeatherServiceReader
from app.outfits.presentation.router import Latitude, Longitude, get_today, get_weekly
from app.outfits.presentation.schemas import TodayOutfitResponse
from app.weather.application.exceptions import InvalidWeatherQueryError, WeatherProviderTimeoutError
from app.weather.application.services import WeatherService
from app.weather.infrastructure.cache import TTLCache
from app.weather.infrastructure.open_meteo import OpenMeteoProvider
from main import app
from tests.test_weather import NOW, forecast_payload


def weather(temperature: float = 20, **changes) -> OutfitWeather:
    """단일 기온의 합성 예보 생성"""
    baseline = OutfitWeather(
        date=date(2026, 11, 4), temperature_min_c=temperature, temperature_max_c=temperature,
        apparent_temperature_min_c=None, apparent_temperature_max_c=None,
        precipitation_probability_percent=0, precipitation_mm=0, snowfall_cm=0,
        wind_speed_m_s=0, uv_index=0, weather_code=0,
    )
    return replace(baseline, **changes)


class OutfitRuleTests(unittest.TestCase):
    def test_temperature_boundaries_select_the_documented_clothes(self):
        """기온 구간 경계에서 상의와 겉옷 선택 확인"""
        cases = [
            (28, "통풍이 좋은 반팔", None), (27.9, "반팔", None),
            (23, "반팔", None), (22.9, "얇은 긴팔", "얇은 가디건"),
            (20, "얇은 긴팔", "얇은 가디건"), (19.9, "긴팔", "가디건"),
            (17, "긴팔", "가디건"), (16.9, "니트", "재킷"),
            (12, "니트", "재킷"), (11.9, "도톰한 니트", "코트"),
            (9, "도톰한 니트", "코트"), (8.9, "보온 이너와 니트", "두꺼운 코트"),
            (5, "보온 이너와 니트", "두꺼운 코트"), (4.9, "보온 이너와 니트", "패딩"),
        ]
        for temperature, top, outerwear in cases:
            with self.subTest(temperature=temperature):
                result = recommend_outfit(weather(temperature))
                self.assertEqual((result.best.top, result.best.outerwear), (top, outerwear))
                self.assertTrue(result.reasons)
                self.assertTrue(result.avoid_reasons)
                self.assertNotEqual(result.best, result.worst)

    def test_apparent_temperature_takes_priority_without_wind_subtraction(self):
        """체감온도를 우선 사용하고 풍속으로 기온을 중복 보정하지 않음"""
        result = recommend_outfit(weather(
            25, apparent_temperature_min_c=4, apparent_temperature_max_c=4, wind_speed_m_s=10,
        ))
        self.assertEqual(result.temperature_basis, TemperatureBasis.APPARENT)
        self.assertEqual(result.reference_temperature_c, 4)
        self.assertEqual(result.best.outerwear, "패딩")

    def test_missing_either_apparent_value_falls_back_to_actual_temperature(self):
        """체감온도 하나가 누락돼도 실제 기온과 기준을 명시"""
        for low, high in [(None, None), (-10, None), (None, -10)]:
            with self.subTest(low=low, high=high):
                result = recommend_outfit(weather(28, apparent_temperature_min_c=low, apparent_temperature_max_c=high))
                self.assertEqual(result.temperature_basis, TemperatureBasis.ACTUAL)
                self.assertEqual(result.reference_temperature_c, 28)
                self.assertIsNone(result.best.outerwear)
                self.assertTrue(any("실제 기온" in reason for reason in result.reasons))

    def test_cold_morning_adds_removable_outerwear_and_accessories(self):
        """아침·낮 기온 차이에 맞춰 겉옷과 방한 준비물 추가"""
        result = recommend_outfit(weather(28, temperature_min_c=4))
        self.assertEqual(result.best.top, "통풍이 좋은 반팔")
        self.assertEqual(result.best.outerwear, "패딩")
        self.assertIn("장갑", result.best.accessories)
        self.assertTrue(any("낮에는 겉옷을 벗어" in text for text in result.precautions))

    def test_rain_probability_boundary_amount_and_weather_code(self):
        """강수확률 경계·누적 강수량·날씨 코드로 우산 준비 판단"""
        cases = [
            ({"precipitation_probability_percent": 59}, False),
            ({"precipitation_probability_percent": 60}, True),
            ({"precipitation_mm": 0.1}, True),
            ({"weather_code": 61}, True),
        ]
        for changes, needs_umbrella in cases:
            with self.subTest(changes=changes):
                result = recommend_outfit(weather(**changes))
                self.assertEqual("우산" in result.best.accessories, needs_umbrella)
                if needs_umbrella:
                    self.assertIn("생활방수", result.best.shoes)
                    self.assertTrue(any("확정이 아니" in text for text in result.precautions))

    def test_snow_overrides_rain_shoes_and_explains_the_worst_choice(self):
        """눈 예보 시 방수·미끄럼 방지 신발과 비추천 이유 제공"""
        for changes in [{"weather_code": 71}, {"snowfall_cm": 1}]:
            with self.subTest(changes=changes):
                result = recommend_outfit(weather(0, precipitation_probability_percent=90, **changes))
                self.assertEqual(result.best.shoes, "미끄럼 방지 방수 신발")
                self.assertEqual(result.worst.shoes, "밑창이 매끄러운 신발")
                self.assertTrue(any("눈길" in reason for reason in result.avoid_reasons))

    def test_wind_and_uv_thresholds_add_only_the_needed_items(self):
        """풍속·자외선 임계값에서 겉옷과 모자 추가"""
        before = recommend_outfit(weather(28, wind_speed_m_s=7.9, uv_index=5.9))
        after = recommend_outfit(weather(28, wind_speed_m_s=8, uv_index=6))
        self.assertIsNone(before.best.outerwear)
        self.assertNotIn("모자", before.best.accessories)
        self.assertEqual(after.best.outerwear, "바람막이")
        self.assertIn("모자", after.best.accessories)

    def test_unknown_optional_metrics_remain_null_with_no_invented_rain(self):
        """누락 정보를 0이나 비 예보로 바꾸지 않음"""
        result = recommend_outfit(weather(
            precipitation_probability_percent=None, precipitation_mm=None, snowfall_cm=None,
            wind_speed_m_s=None, uv_index=None, weather_code=999,
        ))
        self.assertIsNone(result.weather.precipitation_probability_percent)
        self.assertNotIn("우산", result.best.accessories)
        self.assertTrue(any("강수확률 정보" in text for text in result.precautions))
        self.assertTrue(any("풍속 정보" in text for text in result.precautions))

    def test_invalid_weather_values_are_rejected(self):
        """비정상 기온·확률·풍속·체감온도 범위 거부"""
        for changes in [
            {"temperature_min_c": float("nan")}, {"temperature_max_c": float("inf")},
            {"temperature_min_c": 30}, {"precipitation_probability_percent": 101},
            {"wind_speed_m_s": -1}, {"uv_index": -1},
            {"apparent_temperature_min_c": 20, "apparent_temperature_max_c": 10},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                weather(**changes)

    def test_repeated_recommendations_do_not_mutate_shared_clothing_rules(self):
        """우천 추천이 다음 날의 기본 의류 구성을 바꾸지 않음"""
        before = recommend_outfit(weather())
        recommend_outfit(weather(weather_code=61, wind_speed_m_s=10))
        self.assertEqual(recommend_outfit(weather()), before)

    def test_weekly_wardrobe_deduplicates_items_and_omits_empty_outerwear(self):
        """주간 준비물의 중복과 불필요한 null 제거"""
        recommendations = (recommend_outfit(weather(28)),) * 7
        wardrobe = build_weekly_wardrobe(recommendations)
        self.assertEqual(wardrobe.tops, ("통풍이 좋은 반팔",))
        self.assertEqual(wardrobe.outerwear, ())
        self.assertEqual(wardrobe.accessories, ())


class OutfitIntegrationTests(unittest.TestCase):
    def setUp(self):
        """기존 날씨 어댑터와 연결된 옷차림 서비스 준비"""
        self.now = NOW
        self.payload = forecast_payload(self.now)
        self.http = Mock()
        self.http.get.side_effect = lambda *args: copy.deepcopy(self.payload)
        provider = OpenMeteoProvider(self.http, TTLCache(600), clock=lambda: self.now)
        self.weather_service = WeatherService(provider)
        self.reader = WeatherServiceReader(self.weather_service)
        self.service = OutfitService(self.reader)

    def test_today_and_weekly_reuse_the_existing_weather_cache(self):
        """오늘·주간 옷차림과 날씨 API가 같은 예보 캐시 재사용"""
        today = get_today(37.5665, 126.978, self.service)
        weekly = get_weekly(37.5665, 126.978, self.service)
        self.weather_service.get_weekly(37.5665, 126.978)
        self.assertEqual(self.http.get.call_count, 1)
        self.assertEqual(today.data.recommendation, weekly.data.daily[0])
        self.assertEqual(len(weekly.data.daily), 7)
        self.assertEqual((weekly.data.daily[-1].date - weekly.data.daily[0].date).days, 6)
        self.assertEqual(today.data.fetched_at, NOW)
        self.assertEqual(today.data.provider, "Open-Meteo")

    def test_response_serialization_keeps_the_common_envelope_and_null_values(self):
        """공통 응답·중첩 의류·선택 값 null 직렬화 확인"""
        self.payload["daily"]["apparent_temperature_min"] = [None] * 7
        self.payload["daily"]["precipitation_probability_max"] = [None] * 7
        response = get_today(37, 127, self.service)
        payload = response.model_dump(mode="json")
        self.assertEqual(set(payload), {"code", "message", "data", "details"})
        self.assertEqual(payload["code"], "SUCCESS")
        recommendation = payload["data"]["recommendation"]
        self.assertEqual(recommendation["temperature_basis"], "temperature")
        self.assertIsNone(recommendation["weather"]["precipitation_probability_percent"])
        self.assertEqual(payload["data"]["rule_version"], "1.0")
        self.assertEqual(TodayOutfitResponse.model_validate(payload["data"]), response.data)

    def test_today_uses_the_korean_date_even_when_utc_is_previous_day(self):
        """UTC와 날짜가 다른 시각에도 한국 날짜로 추천"""
        self.now = datetime(2026, 11, 4, 15, 1, tzinfo=timezone.utc)
        self.payload = forecast_payload(self.now)
        result = self.service.get_today(37, 127)
        self.assertEqual(result.recommendation.date, date(2026, 11, 5))

    def test_invalid_coordinates_fail_before_any_external_request(self):
        """기존 날씨 서비스의 좌표 검증 재사용"""
        with self.assertRaises(InvalidWeatherQueryError):
            self.service.get_today(91, 127)
        self.http.get.assert_not_called()

    def test_provider_failure_remains_a_common_error_instead_of_sample_recommendations(self):
        """날씨 조회 실패 시 임의 추천 없이 기존 오류 전파"""
        self.http.get.side_effect = WeatherProviderTimeoutError()
        with self.assertRaises(WeatherProviderTimeoutError) as caught:
            self.service.get_today(37, 127)
        response = handle_app_error(Request({"type": "http"}), caught.exception)
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(payload["code"], "WEATHER_TIMEOUT")
        self.assertIsNone(payload["data"])

    def test_missing_reordered_or_duplicate_dates_are_rejected(self):
        """7일 중 누락·순서 변경·중복 날짜가 있으면 추천 거부"""
        snapshot = self.reader.get_forecast(37, 127)
        cases = [snapshot.days[:6], snapshot.days[::-1], (snapshot.days[0],) * 7]
        for days in cases:
            with self.subTest(days=days):
                reader = Mock()
                reader.get_forecast.return_value = replace(snapshot, days=days)
                with self.assertRaises(OutfitForecastError) as caught:
                    OutfitService(reader).get_weekly(37, 127)
                response = handle_app_error(Request({"type": "http"}), caught.exception)
                self.assertEqual(response.status_code, 502)
                self.assertEqual(json.loads(response.body)["code"], "OUTFIT_INVALID_FORECAST")

    def test_weather_adapter_converts_invalid_recommendation_input_to_a_public_error(self):
        """추천에 부적합한 체감온도 범위는 공통 업무 오류로 변환"""
        self.payload["daily"]["apparent_temperature_min"] = [30] * 7
        with self.assertRaises(OutfitForecastError):
            self.service.get_today(37, 127)

    def test_api_query_types_reject_out_of_range_and_non_finite_coordinates(self):
        """API 좌표 타입이 범위 밖 값과 NaN·무한대를 거부"""
        for annotation, value in [(Latitude, 91), (Longitude, 181), (Latitude, float("nan")), (Longitude, float("inf"))]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                TypeAdapter(annotation).validate_python(value)

    def test_swagger_documents_outfit_data_and_shared_error_responses(self):
        """추천 데이터 스키마·필드 설명·공통 오류 문서 확인"""
        document = app.openapi()
        for suffix, data_schema in [("today", "TodayOutfitResponse"), ("weekly", "WeeklyOutfitResponse")]:
            operation = document["paths"][f"/api/v1/outfits/{suffix}"]["get"]
            response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
            response = document["components"]["schemas"][response_ref.split("/")[-1]]
            self.assertEqual(response["properties"]["data"]["$ref"], f"#/components/schemas/{data_schema}")
            examples = operation["responses"]["502"]["content"]["application/json"]["examples"]
            self.assertIn("OUTFIT_INVALID_FORECAST", examples)
            self.assertIn("WEATHER_INVALID_RESPONSE", examples)
        for name in ["OutfitRecommendationResponse", "OutfitLookResponse", "WeeklyWardrobeResponse", "OutfitWeatherResponse"]:
            for field in document["components"]["schemas"][name]["properties"].values():
                self.assertTrue(field.get("description"))


if __name__ == "__main__":
    unittest.main()
