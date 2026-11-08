"""원피스·빈값 계약을 생성, 공개 응답, 주간 집계, 캐시 경계에서 확인한다."""

# 표준 라이브러리
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

# 외부 라이브러리
from pydantic import TypeAdapter

# 프로젝트 모듈
from app.common.config import Settings
from app.outfits.application.exceptions import OutfitLlmResponseError
from app.outfits.bootstrap import get_cached_outfit_service, get_personalized_outfit_cache
from app.outfits.domain.models import OutfitLook, OutfitType
from app.outfits.domain.rules import build_weekly_wardrobe
from app.outfits.infrastructure.recommenders import GeminiOutfitRecommender, OllamaOutfitRecommender
from app.outfits.infrastructure.schemas import GeneratedLook
from app.outfits.infrastructure.prompts import LOOK_EXAMPLES, build_messages
from app.outfits.presentation.schemas import TodayOutfitResponse
from tests import test_outfits as fixtures
from tests.test_outfits import generated_content, weather


def dress(name="면 원피스"):
    return {"outfit_type": "one_piece", "top": None, "bottom": None, "one_piece": name,
            "outerwear": None, "shoes": "운동화", "accessories": ["모자"]}


class OutfitContractTests(unittest.TestCase):
    def setUp(self):
        self.day = weather()
        self.client = Mock()
        self.recommender = OllamaOutfitRecommender(self.client, "test-model")

    def payload(self):
        return json.loads(generated_content([self.day.date.isoformat()]))

    def test_one_piece_survives_local_cloud_and_public_response(self):
        payload = self.payload()
        payload["days"][0]["best"] = dress()
        self.client.chat.return_value = json.dumps(payload, ensure_ascii=False)
        for recommender in (self.recommender, GeminiOutfitRecommender(self.client, "test-cloud")):
            with self.subTest(provider=type(recommender).__name__):
                look = recommender.recommend((self.day,)).recommendations[0].best
                self.assertEqual(look.outfit_type, OutfitType.ONE_PIECE)
                self.assertIsNone(look.top)
                self.assertIsNone(look.bottom)
                self.assertEqual(look.one_piece, "면 원피스")
        fixture = fixtures.OutfitIntegrationTests()
        fixture.setUp()
        forecast = fixture.service.get_today(37, 127)
        look = self.recommender.recommend((self.day,)).recommendations[0].best
        result = replace(forecast, recommendation=replace(forecast.recommendation, best=look))
        body = TodayOutfitResponse.from_result(result).model_dump(mode="json")["recommendation"]["best"]
        self.assertEqual(body["outfit_type"], "one_piece")
        self.assertIsNone(body["top"])
        self.assertIsNone(body["bottom"])
        self.assertEqual(body["one_piece"], "면 원피스")

    def test_placeholder_names_are_rejected_in_every_clothing_slot(self):
        for placeholder in ("null", " NONE ", "N/A", "없음", "-"):
            for slot in ("top", "bottom", "outerwear", "shoes", "accessories"):
                with self.subTest(placeholder=placeholder, slot=slot):
                    payload = self.payload()
                    payload["days"][0]["best"][slot] = [placeholder] if slot == "accessories" else placeholder
                    self.client.chat.return_value = json.dumps(payload)
                    with self.assertRaises(OutfitLlmResponseError):
                        self.recommender.recommend((self.day,))
        payload = self.payload()
        payload["days"][0]["best"] = dress("null")
        self.client.chat.return_value = json.dumps(payload)
        with self.assertRaises(OutfitLlmResponseError):
            self.recommender.recommend((self.day,))

    def test_outfit_type_and_parts_must_agree(self):
        for look in (dress() | {"top": "셔츠"}, dress() | {"bottom": "바지"}, dress() | {"one_piece": None},
                     dress() | {"outfit_type": "separates"}, self.payload()["days"][0]["best"] | {"one_piece": "원피스"}):
            with self.subTest(look=look):
                payload = self.payload()
                payload["days"][0]["best"] = look
                self.client.chat.return_value = json.dumps(payload)
                with self.assertRaises(OutfitLlmResponseError):
                    self.recommender.recommend((self.day,))

    def test_different_one_piece_names_are_not_treated_as_identical_looks(self):
        payload = self.payload()
        payload["days"][0].update(best=dress("면 원피스"), worst=dress("울 원피스"))
        self.client.chat.return_value = json.dumps(payload)
        result = self.recommender.recommend((self.day,))
        self.assertNotEqual(result.recommendations[0].best.one_piece, result.recommendations[0].worst.one_piece)

    def test_weekly_wardrobe_deduplicates_one_pieces_without_null_items(self):
        payload = self.payload()
        self.client.chat.return_value = json.dumps(payload)
        separates = self.recommender.recommend((self.day,)).recommendations[0]
        payload["days"][0]["best"] = dress()
        self.client.chat.return_value = json.dumps(payload)
        one_piece = self.recommender.recommend((self.day,)).recommendations[0]
        wardrobe = build_weekly_wardrobe((separates, one_piece, one_piece))
        self.assertEqual(wardrobe.tops, ("블루 셔츠",))
        self.assertEqual(wardrobe.bottoms, ("면바지",))
        self.assertEqual(wardrobe.one_pieces, ("면 원피스",))

    def test_legacy_cached_separates_still_parse_without_new_fields(self):
        look = TypeAdapter(OutfitLook).validate_json(json.dumps({
            "top": "셔츠", "bottom": "바지", "outerwear": None, "shoes": "운동화", "accessories": [],
        }))
        self.assertEqual(look.outfit_type, OutfitType.SEPARATES)
        self.assertIsNone(look.one_piece)
        with self.assertRaises(ValueError):
            OutfitLook("셔츠", "null", None, "운동화")

    def test_prompt_examples_are_valid_but_do_not_change_requested_dates(self):
        for example in LOOK_EXAMPLES:
            GeneratedLook.model_validate(example)
        self.client.chat.return_value = generated_content([self.day.date.isoformat()])
        self.recommender.recommend((self.day,))
        _, messages, schema = self.client.chat.call_args.args
        content = json.loads(messages[1]["content"])
        self.assertEqual(content["output_schema"], schema)
        self.assertEqual(content["weather_days"][0]["date"], self.day.date.isoformat())
        labels = content["weather_days"][0]["temperature_labels_ko"]
        self.assertEqual(labels["실제기온_최고_C"], self.day.temperature_max_c)
        self.assertIsNone(labels["체감온도_최고_C"])
        self.assertIn("description", schema["$defs"]["GeneratedLook"]["properties"]["shoes"])

    def test_sampling_changes_separate_common_and_personal_cache_scopes(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.outfits.bootstrap.get_sigungu_resolver", return_value=Mock()):
            scopes = []
            for top_p, min_p in ((None, None), (0.8, None), (0.8, 0.03)):
                get_cached_outfit_service.cache_clear()
                get_personalized_outfit_cache.cache_clear()
                settings = Settings("test", Path(directory) / "cache.db", llm_model="test", llm_top_p=top_p, llm_min_p=min_p)
                with patch("app.outfits.bootstrap.get_settings", return_value=settings):
                    scopes.append((get_cached_outfit_service()._scope, get_personalized_outfit_cache()._scope))
            get_cached_outfit_service.cache_clear()
            get_personalized_outfit_cache.cache_clear()
        self.assertEqual(len({scope[0] for scope in scopes}), 3)
        self.assertEqual(len({scope[1] for scope in scopes}), 3)
