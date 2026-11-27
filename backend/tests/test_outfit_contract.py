"""원피스·빈값 계약을 생성, 공개 응답, 주간 집계, 캐시 경계에서 확인한다."""

# 표준 라이브러리
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

# 외부 라이브러리
from pydantic import TypeAdapter

# 프로젝트 모듈
from app.common.config import Settings
from app.outfits.application.exceptions import OutfitLlmResponseError
from app.outfits.bootstrap import get_cached_outfit_service, get_personalized_outfit_cache
from app.outfits.domain.models import AvoidItem, ClothingPreference, OutfitLook, OutfitPreferences, OutfitType
from app.outfits.domain.rules import build_weekly_wardrobe
from app.outfits.infrastructure.recommenders import GeminiOutfitRecommender, OllamaOutfitRecommender, PersonalizationChatClient
from app.outfits.infrastructure.schemas import GeneratedLook
from app.outfits.infrastructure.prompts import LOOK_EXAMPLES
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

    def test_menswear_repairs_dresses_in_either_look_without_rejecting_shared_one_piece(self):
        preferences = OutfitPreferences(clothing_preference=ClothingPreference.MENSWEAR)
        recommender = OllamaOutfitRecommender(
            PersonalizationChatClient(self.client, preferences), "test-model", repair_attempts=1,
        )
        for slot in ("best", "worst"):
            with self.subTest(slot=slot):
                self.client.reset_mock()
                wrong, corrected = self.payload(), self.payload()
                wrong["days"][0][slot] = dress()
                corrected["days"][0]["best"] = dress("작업용 점프수트")
                corrected["days"][0]["worst"]["top"] = "얇은 드레스 셔츠"
                corrected["days"][0]["worst"]["shoes"] = "드레스 슈즈"
                self.client.chat.side_effect = [json.dumps(wrong), json.dumps(corrected)]

                look = recommender.recommend((self.day,)).recommendations[0].best

                self.assertEqual(look.one_piece, "작업용 점프수트")
                first, second = [json.loads(call.args[1][1]["content"]) for call in self.client.chat.call_args_list]
                self.assertTrue(first["look_examples"])
                self.assertNotIn("면 원피스", json.dumps(first["look_examples"], ensure_ascii=False))
                self.assertIn(slot, second["answer_checks"][0])
                self.assertIn("면 원피스", second["answer_checks"][0])

    def test_personalized_outfits_reject_explicit_opposite_style_and_keep_shared_items(self):
        for style, conflicting_names in (
            (ClothingPreference.WOMENSWEAR, ("남성 린넨 재킷", "남성 전용 재킷", "Men\u2019s jacket", "네이비 남성 재킷")),
            (ClothingPreference.MENSWEAR, ("여성 린넨 재킷", "여성 전용 재킷", "Women's jacket",
                                          "원 피스", "high heels", "흰색 여성 블라우스")),
        ):
            preferences = OutfitPreferences(clothing_preference=style)
            recommender = OllamaOutfitRecommender(
                PersonalizationChatClient(self.client, preferences), "test-model",
            )
            for side in ("best", "worst"):
                for name in conflicting_names:
                    with self.subTest(preference=style, side=side, item=name):
                        payload = self.payload()
                        payload["days"][0][side]["outerwear"] = name
                        self.client.chat.return_value = json.dumps(payload)
                        with self.assertRaises(OutfitLlmResponseError):
                            recommender.recommend((self.day,))

            for name in ("공용 재킷", "네이비 남성·여성 공용 재킷", "남녀 공용 재킷"):
                with self.subTest(preference=style, shared=name):
                    payload = self.payload()
                    payload["days"][0]["best"]["outerwear"] = name
                    self.client.chat.return_value = json.dumps(payload)
                    self.assertEqual(recommender.recommend((self.day,)).recommendations[0].best.outerwear, name)

    def test_one_piece_label_rejects_dress_shirts_and_shoes_but_keeps_valid_types(self):
        for name in ("흰색 남성용 드레스 셔츠", "검정 드레스 구두", "navy dress shirt", "brown dress shoes"):
            with self.subTest(name=name), self.assertRaises(OutfitLlmResponseError):
                payload = self.payload()
                payload["days"][0]["best"] = dress(name)
                self.client.chat.return_value = json.dumps(payload)
                self.recommender.recommend((self.day,))

        for name in ("검정 체크 원피스", "공용 점프슈트", "khaki jumpsuit"):
            with self.subTest(name=name):
                payload = self.payload()
                payload["days"][0]["best"] = dress(name)
                payload["days"][0]["worst"]["top"] = "흰색 드레스 셔츠"
                self.client.chat.return_value = json.dumps(payload)
                recommendation = self.recommender.recommend((self.day,)).recommendations[0]
                self.assertEqual(recommendation.best.one_piece, name)
                self.assertEqual(recommendation.worst.top, "흰색 드레스 셔츠")

    def test_personalized_avoid_items_trigger_repair_for_best_only(self):
        preferences = OutfitPreferences(avoid_items=tuple(AvoidItem))
        recommender = OllamaOutfitRecommender(
            PersonalizationChatClient(self.client, preferences), "test-model", repair_attempts=1,
        )
        for slot, name in (
            ("bottom", "테니스 스커트"), ("one_piece", "린넨 원피스"), ("bottom", "러닝 쇼츠"),
            ("shoes", "트레킹 샌들"), ("shoes", "하이 힐"), ("top", "슬리브리스 셔츠"),
            ("shoes", "굽 높은 구두"), ("shoes", "굽이 높은 구두"),
        ):
            with self.subTest(item=name):
                self.client.reset_mock()
                wrong, corrected = self.payload(), self.payload()
                wrong_day, corrected_day = wrong["days"][0], corrected["days"][0]
                if slot == "one_piece":
                    wrong_day["best"] = dress(name)
                    corrected_day["worst"] = dress(name)
                else:
                    wrong_day["best"][slot] = name
                    corrected_day["worst"][slot] = name
                corrected_day["best"]["top"] = "드레스 셔츠"
                self.client.chat.side_effect = [json.dumps(wrong), json.dumps(corrected)]

                day = recommender.recommend((self.day,)).recommendations[0]

                self.assertEqual(day.best.top, "드레스 셔츠")
                self.assertEqual(getattr(day.worst, slot), name)
                self.assertEqual(self.client.chat.call_count, 2)
                first = json.loads(self.client.chat.call_args_list[0].args[1][1]["content"])
                self.assertTrue(all(look["outfit_type"] == "separates" for look in first["look_examples"]))
                repair = json.loads(self.client.chat.call_args.args[1][1]["content"])
                self.assertIn(name, repair["answer_checks"][0])

    def test_personalized_hot_day_retries_unsupported_low_apparent_temperature(self):
        recommender = OllamaOutfitRecommender(
            PersonalizationChatClient(self.client, OutfitPreferences()), "test-model", repair_attempts=1,
        )
        for minimum, maximum, evidence in (
            (None, None, "체감온도는 제공되지 않았습니다"),
            (None, 36, "체감 최저는 제공되지 않았습니다"),
            (32, None, "체감 최고는 제공되지 않았습니다"),
        ):
            with self.subTest(apparent_minimum=minimum, apparent_maximum=maximum):
                self.client.reset_mock()
                day = replace(self.day, temperature_min_c=27, temperature_max_c=34,
                              apparent_temperature_min_c=minimum, apparent_temperature_max_c=maximum)
                wrong, corrected = self.payload(), self.payload()
                wrong["days"][0]["reasons"] = ["낮은 체감온도에 맞는 니트입니다."]
                corrected["days"][0]["reasons"] = ["실제 기온 27~34°C에 맞춰 가벼운 옷을 골랐습니다."]
                self.client.chat.side_effect = [json.dumps(wrong), json.dumps(corrected)]

                generated = recommender.recommend((day,)).recommendations[0]

                self.assertIn(corrected["days"][0]["reasons"][0], generated.reasons)
                self.assertEqual(self.client.chat.call_count, 2)
                first, second = [json.loads(call.args[1][1]["content"]) for call in self.client.chat.call_args_list]
                provided_day = first["weather_days"][0]
                self.assertEqual(provided_day["temperature_basis"], "temperature")
                self.assertEqual(provided_day["apparent_temperature_min_c"], minimum)
                self.assertEqual(provided_day["apparent_temperature_max_c"], maximum)
                self.assertIn("실제 기온 27~34°C", provided_day["temperature_evidence"])
                self.assertIn(evidence, second["answer_checks"][0])
                if minimum is not None or maximum is not None:
                    label, value = ("최저", minimum) if minimum is not None else ("최고", maximum)
                    self.assertIn(f"체감 {label} {value:g}°C", second["answer_checks"][0])

    def test_personalized_partial_low_apparent_temperature_does_not_trigger_repair(self):
        recommender = OllamaOutfitRecommender(
            PersonalizationChatClient(self.client, OutfitPreferences()), "test-model", repair_attempts=1,
        )
        for minimum, maximum in ((18, None), (None, 18), (0, None)):
            with self.subTest(apparent_minimum=minimum, apparent_maximum=maximum):
                self.client.reset_mock()
                day = replace(self.day, temperature_min_c=27, temperature_max_c=34,
                              apparent_temperature_min_c=minimum, apparent_temperature_max_c=maximum)
                payload = self.payload()
                label, value = ("최저", minimum) if minimum is not None else ("최고", maximum)
                explanation = f"낮은 체감온도에 맞는 니트입니다. 제공된 체감 {label}는 {value:g}°C입니다."
                payload["days"][0]["reasons"] = [explanation]
                self.client.chat.side_effect = None
                self.client.chat.return_value = json.dumps(payload)

                generated = recommender.recommend((day,)).recommendations[0]

                self.assertIn(explanation, generated.reasons)
                self.client.chat.assert_called_once()

    def test_rain_explanation_retries_unsupported_protection_from_plain_clothes(self):
        day = replace(self.day, precipitation_mm=12, precipitation_probability_percent=80)
        recommender = OllamaOutfitRecommender(self.client, "test-model", repair_attempts=1)
        for field, item, sentence in (
            ("reasons", "경량 점퍼", "경량 점퍼는 비에 젖지 않도록 보호하면서도 움직임에 방해가 없습니다."),
            ("reasons", "코트", "코트는 비를 막아 주는 역할을 합니다."),
            ("reasons", "가벼운 코트", "가벼운 코트는 비와 바람을 막아주며, 우산은 비를 효과적으로 방지합니다."),
            ("avoid_reasons", "가벼운 코트", "가벼운 코트는 비와 바람을 방지합니다."),
            ("reasons", "코트", "우산은 비를 막아 주고 코트도 비를 막아 줍니다."),
            ("reasons", "코트", "우산은 비를 막아 주고 코트는 비에 젖지 않도록 보호해 줍니다."),
            ("avoid_reasons", "코트", "우산은 비를 막아 주고 코트도 비를 막아 줍니다."),
            ("reasons", "코트", "우산은 비를 막아 주지 않지만 코트는 비를 막아 줍니다."),
            ("reasons", "코트", "코트는 비를 막아 주고 우산은 비를 막아 주지 않습니다."),
            ("reasons", "코트", "우산은 비를 막아 주고 코트는 비를 막아 주며 신발도 비를 막아 줍니다."),
        ):
            with self.subTest(field=field, garment=item):
                self.client.reset_mock()
                wrong, corrected = self.payload(), self.payload()
                look = "best" if field == "reasons" else "worst"
                wrong["days"][0][look]["outerwear"] = item
                wrong["days"][0][look]["accessories"] = ["우산"]
                wrong["days"][0][field] = [sentence]
                best = corrected["days"][0]["best"]
                best["outerwear"] = "방수 재킷"
                best["accessories"] = ["우산"]
                corrected["days"][0]["reasons"] = [
                    "방수 재킷은 비를 막아 주고 체온을 유지하는 데 도움이 됩니다.",
                    "우산이 비를 막아 주고 바지는 보온에 도움이 됩니다.",
                ]
                self.client.chat.side_effect = [json.dumps(wrong), json.dumps(corrected)]

                result = recommender.recommend((day,)).recommendations[0]

                self.assertEqual(result.best.outerwear, "방수 재킷")
                first, second = [json.loads(call.args[1][1]["content"]) for call in self.client.chat.call_args_list]
                self.assertIn("우비", first["rain_protection"])
                self.assertIn(look, second["answer_checks"][0])

    def test_rain_explanation_accepts_valid_protection_without_repair(self):
        day = replace(self.day, precipitation_mm=12, precipitation_probability_percent=80)
        recommender = OllamaOutfitRecommender(self.client, "test-model", repair_attempts=1)
        for field in ("reasons", "avoid_reasons"):
            for sentence in (
                "코트는 비를 막아 주는 기능이 없습니다.",
                "코트는 비를 막아주는 기능은 없고 보온을 돕습니다.",
                "코트는 비를 막아 주지 않습니다.",
                "코트는 비를 막아 줄 수 없습니다.",
                "코트는 비에 젖지 않도록 보호해 주는 기능이 없습니다.",
                "코트는 비를 막아 주는 기능이 없고 우산은 비를 막아 줍니다.",
                "우산은 비를 막아 주고 코트는 비를 막아 주는 기능이 없습니다.",
                "우산은 비를 막아 주고 코트는 비를 막아 주지 않습니다.",
                "우산은 비를 막아 주고 코트가 비에 젖지 않도록 보호해 줍니다.",
                "우산은 비를 막고 코트가 비에 젖지 않도록 보호해 줍니다.",
            ):
                with self.subTest(field=field, explanation=sentence):
                    self.client.reset_mock()
                    payload = self.payload()
                    look = "best" if field == "reasons" else "worst"
                    payload["days"][0][look]["outerwear"] = "코트"
                    payload["days"][0][look]["accessories"] = ["우산"]
                    payload["days"][0][field] = [sentence]
                    self.client.chat.side_effect = None
                    self.client.chat.return_value = json.dumps(payload)

                    generated = recommender.recommend((day,)).recommendations[0]

                    self.assertIn(sentence, getattr(generated, field))
                    self.client.chat.assert_called_once()

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

    def test_common_and_personal_prompts_request_colors_and_designs_for_today_and_weekly(self):
        for count in (1, 7):
            days = tuple(replace(self.day, date=self.day.date + timedelta(days=index)) for index in range(count))
            payload = json.loads(generated_content([day.date.isoformat() for day in days]))
            for day in payload["days"]:
                day.update(best=LOOK_EXAMPLES[0], worst=LOOK_EXAMPLES[1])
            self.client.chat.return_value = json.dumps(payload)
            personal = OllamaOutfitRecommender(
                PersonalizationChatClient(self.client, OutfitPreferences()), "test-model",
            )
            for recommender in (self.recommender, GeminiOutfitRecommender(self.client, "test-cloud"), personal):
                with self.subTest(days=count, client=type(recommender).__name__, personal=recommender is personal):
                    generated = recommender.recommend(days)
                    _, messages, _ = self.client.chat.call_args.args
                    self.assertIn("best와 worst", messages[0]["content"])
                    self.assertIn("top, bottom, outerwear, one_piece의 이름에 대표 바탕색과 눈에 보이는 디자인 특징", messages[0]["content"])
                    self.assertIn("상의와 원피스·점프수트는 의류에 맞는 네크라인이나 칼라", messages[0]["content"])
                    self.assertIn("크루넥(라운드넥)", messages[0]["content"])
                    self.assertIn("셔츠 칼라, 폴로 칼라, 스탠드 칼라", messages[0]["content"])
                    self.assertIn("줄무늬나 체크", messages[0]["content"])
                    self.assertIn("무늬 없는 조합도 허용", messages[0]["content"])
                    self.assertEqual(json.loads(messages[1]["content"])["look_examples"], list(LOOK_EXAMPLES))
                    self.assertEqual(len(generated.recommendations), count)
                    for recommendation in generated.recommendations:
                        self.assertEqual(recommendation.best.top, "네이비 줄무늬 크루넥 긴팔 티셔츠")
                        self.assertEqual(recommendation.best.bottom, "베이지 투턱 일자핏 긴바지")
                        self.assertEqual(recommendation.best.outerwear, "카키 싱글버튼 트렌치코트")
                        self.assertEqual(recommendation.best.shoes, "흰색 로우컷 운동화")
                        self.assertEqual(recommendation.worst.one_piece, "검정 체크 스퀘어넥 긴팔 플레어 원피스")

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
