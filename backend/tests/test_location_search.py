"""부분 일치 검색, 복합 조건, 페이지 경계와 국내 자료 재색인을 임시 DB로 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from app.weather.application.exceptions import InvalidWeatherQueryError
from app.weather.application.services import WeatherService
from app.weather.domain.models import Location
from app.weather.infrastructure.location_catalog import SQLiteLocationCatalog, SQLiteLocationSearch


def record(identifier, name, search_text, priority=3, admin1="서울특별시", admin2=None):
    location = Location(identifier, name, 37.5, 127.0, "KR", "대한민국", admin1, admin2, "Asia/Seoul")
    return {"location": asdict(location), "search_text": search_text, "name_search": name, "priority": priority, "population": 1}


class LocationSearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "search.db"
        self.records = (
            record(1, "서울특별시", "서울 서울시 서울특별시 Seoul", 0),
            record(2, "강남구", "강남구 서울특별시", admin2="강남구"),
            record(3, "역삼동", "역삼동 강남구 서울특별시", 5, admin2="강남구"),
            record(4, "남서울동", "남서울동 경기도 성남시", 10, "경기도", "성남시"),
            record(5, "광주광역시", "광주광역시 Gwangju", 1, "광주광역시"),
            record(6, "광주시", "광주시 경기도 Gwangju", 3, "경기도", "광주시"),
            record(7, "부산광역시", "부산광역시 Busan", 1, "부산광역시"),
            record(8, "백분율%동", "백분율%동", 10, "경기도"),
            record(9, "밑줄_동", "밑줄_동", 10, "경기도"),
        )
        self.index = SQLiteLocationSearch(self.path, self.records, "v1")

    def test_contains_matches_middle_names_and_parent_regions(self):
        result = self.index.search("서울", 50, 0)
        self.assertEqual({row.id for row in result.locations}, {1, 2, 3, 4})
        self.assertEqual(result.total, 4)
        self.assertEqual(result.locations[0].id, 1)
        self.assertEqual(self.index.search("%서울%", 50, 0).locations, result.locations)
        self.assertEqual(self.index.search("SEOUL", 50, 0).locations[0].id, 1)

    def test_all_tokens_must_match_and_order_does_not_matter(self):
        first = self.index.search("서울 강남", 50, 0)
        second = self.index.search("강남   서울", 50, 0)
        self.assertEqual(first.locations, second.locations)
        self.assertEqual({row.id for row in first.locations}, {2, 3})

    def test_pagination_is_stable_and_exposes_the_complete_result(self):
        first, second = self.index.search("서울", 2, 0), self.index.search("서울", 2, 2)
        self.assertEqual(first.total, second.total)
        self.assertTrue(first.has_more)
        self.assertFalse(second.has_more)
        self.assertEqual(len({row.id for row in (*first.locations, *second.locations)}), 4)
        beyond = self.index.search("서울", 2, 4)
        self.assertEqual(beyond.locations, ())
        self.assertEqual(beyond.total, 4)
        self.assertFalse(beyond.has_more)

    def test_gwangju_names_are_disambiguated_by_administrative_context(self):
        self.assertEqual({row.id for row in self.index.search("광주", 50, 0).locations}, {5, 6})
        self.assertEqual([row.id for row in self.index.search("경기 광주", 50, 0).locations], [6])

    def test_wildcard_and_sql_characters_are_literals(self):
        self.assertEqual(self.index.search("밑줄_", 50, 0).total, 1)
        self.assertEqual(self.index.search("밑줄%동", 50, 0).total, 0)
        self.assertEqual(self.index.search("' OR 1=1 --", 50, 0).total, 0)
        for query in ("%%", " ", "%서%"):
            with self.assertRaises(InvalidWeatherQueryError):
                self.index.search(query, 10, 0)

    def test_service_persists_selected_search_candidates_without_external_requests(self):
        provider = Mock()
        catalog = SQLiteLocationCatalog(self.path)
        service = WeatherService(provider, catalog, self.index)
        result = service.search_locations("서울 강남", 1, 1)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.offset, 1)
        self.assertEqual(catalog.get(result.locations[0].id), result.locations[0])
        provider.search_locations.assert_not_called()

    def test_revision_rebuild_keeps_saved_locations(self):
        catalog = SQLiteLocationCatalog(self.path)
        saved = Location(999, "이전 선택", 36, 128, "KR")
        catalog.save((saved,))
        self.assertEqual(self.index.search("서울", 50, 0).total, 4)
        rebuilt = SQLiteLocationSearch(self.path, (self.records[0],), "v2")
        self.assertEqual(rebuilt.search("서울", 50, 0).total, 1)
        self.assertEqual(catalog.get(999), saved)

    def test_concurrent_initialization_returns_one_consistent_index(self):
        indexes = [SQLiteLocationSearch(self.path, self.records, "v1") for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            totals = list(pool.map(lambda index: index.search("서울", 50, 0).total, indexes))
        self.assertEqual(totals, [4, 4, 4, 4])

    def test_invalid_page_parameters_are_rejected(self):
        for limit, offset in ((0, 0), (51, 0), (10, -1), (10, 1000001)):
            with self.assertRaises(InvalidWeatherQueryError):
                self.index.search("서울", limit, offset)
