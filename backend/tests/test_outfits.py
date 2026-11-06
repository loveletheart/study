"""모의 로컬 LLM으로 날씨 연결과 옷차림 응답 검증."""

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
from app.outfits.application.services.outfit_service import OutfitService
from app.outfits.domain.models import OutfitWeather, TemperatureBasis
from app.outfits.infrastructure.ollama_client import OllamaClient
from app.outfits.infrastructure.ollama_recommender import OllamaOutfitRecommender
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
        wind_speed_m_s=0, uv_index=0, weather_code=0, description="맑음",
    )
    return replace(baseline, **changes)


def generated_content(dates: list[str], outerwear: str | None = "재킷") -> str:
    """테스트에서만 사용하는 합성 LLM 응답 생성"""
    return json.dumps({"days": [{
        "date": day,
        "best": {"outfit_type": "separates", "one_piece": None, "top": "블루 셔츠", "bottom": "면바지", "outerwear": outerwear, "shoes": "생활방수 운동화", "accessories": ["우산"]},
        "worst": {"outfit_type": "separates", "one_piece": None, "top": "민소매", "bottom": "반바지", "outerwear": None, "shoes": "슬리퍼", "accessories": []},
        "reasons": ["아침의 낮은 기온과 강수 가능성을 함께 고려한 구성입니다."],
        "avoid_reasons": ["얇은 옷만 입으면 아침·저녁에 추울 수 있습니다."],
        "precautions": ["외출 전 최신 예보를 확인하세요."],
    } for day in dates]}, ensure_ascii=False)


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
        self.llm = Mock(spec=OllamaClient)
        self.llm.chat.side_effect = lambda model, messages, schema: generated_content([
            day["date"] for day in json.loads(messages[1]["content"])["weather_days"]
        ])
        self.recommender = OllamaOutfitRecommender(self.llm, "test-local-model")
        self.service = OutfitService(self.reader, self.recommender)

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
        self.assertEqual(self.llm.chat.call_count, 2)
        self.assertEqual(self.llm.chat.call_args.args[2]["properties"]["days"]["minItems"], 7)

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
        self.assertEqual(payload["data"]["engine"]["model"], "test-local-model")
        self.assertNotIn("rule_version", payload["data"])
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
                    OutfitService(reader, self.recommender).get_weekly(37, 127)
                response = handle_app_error(Request({"type": "http"}), caught.exception)
                self.assertEqual(response.status_code, 502)
                self.assertEqual(json.loads(response.body)["code"], "OUTFIT_INVALID_FORECAST")
        self.llm.chat.assert_not_called()

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
