"""GeoNames 국내 공개 목록으로 부분 일치 검색 자료를 재현한다. 서버는 다운로드하지 않는다."""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata
from urllib.request import urlopen
from zipfile import ZipFile

SOURCE_URL = "https://download.geonames.org/export/dump/KR.zip"
OUTPUT = Path(__file__).resolve().parents[1] / "app/weather/infrastructure/data"
PRIORITIES = {"PPLC": 0, "PPLA": 1, "ADM1": 2, "ADM2": 3, "PPLA2": 4, "ADM3": 5, "PPLA3": 6, "ADM4": 7, "PPLA4": 8, "PPLX": 9, "PPL": 10}


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def names(row):
    return list(dict.fromkeys([row[1], row[2], *[name for name in row[3].split(",") if re.search("[가-힣]", name)]]))


def display(row):
    if re.search("[가-힣]", row[1]):
        return row[1]
    korean = [name for name in names(row) if re.fullmatch(r"[가-힣0-9·ㆍ\s()\-]+", name)]
    return max(korean, key=len) if korean else row[1]


def build(data):
    with ZipFile(io.BytesIO(data)) as archive:
        if archive.getinfo("KR.txt").file_size > 128 * 1024 * 1024:
            raise ValueError("국내 지역 목록 크기 제한 초과")
        rows = [line.split("\t") for line in archive.read("KR.txt").decode("utf-8").splitlines()]
    if not rows or any(len(row) != 19 for row in rows):
        raise ValueError("GeoNames 원본 필드 형식 오류")
    rows = [row for row in rows if row[8] == "KR" and row[6] in {"A", "P"}]
    parents = {(int(row[7][-1]), tuple(row[10:10 + int(row[7][-1])])): row for row in rows if re.fullmatch(r"ADM[1-4]", row[7])}
    selected = {}
    for row in rows:
        identifier, latitude, longitude = int(row[0]), float(row[4]), float(row[5])
        if identifier <= 0 or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("잘못된 지역 식별자 또는 좌표")
        ancestors = [parents[(level, tuple(row[10:10 + level]))] for level in range(1, 5) if (level, tuple(row[10:10 + level])) in parents]
        admin1 = parents.get((1, (row[10],)))
        admin2 = parents.get((2, tuple(row[10:12])))
        name = display(row)
        location = {"id": identifier, "name": name, "latitude": latitude, "longitude": longitude, "country_code": "KR", "country": "대한민국", "admin1": display(admin1) if admin1 else None, "admin2": display(admin2) if admin2 else None, "timezone": row[17] or "Asia/Seoul"}
        priority = PRIORITIES.get(row[7], 11)
        record = {"location": location, "search_text": normalize(" ".join(names(row) + [value for parent in ancestors for value in names(parent)])), "name_search": normalize(name), "priority": priority, "population": max(0, int(row[14] or 0))}
        # 같은 행정 계층·동일 표시 이름의 도시/행정구역 중복은 우선순위로 합친다.
        key = (name, *row[10:14])
        if key not in selected or (priority, identifier) < (selected[key]["priority"], selected[key]["location"]["id"]):
            selected[key] = record
    return sorted(selected.values(), key=lambda record: record["location"]["id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        with urlopen(SOURCE_URL, timeout=30) as response:
            data = response.read(20_000_001)
    elif args.source_zip:
        data = args.source_zip.read_bytes()
    else:
        parser.error("--source-zip 또는 --download를 지정하세요.")
    if len(data) > 20_000_000:
        raise ValueError("다운로드 크기 제한 초과")
    records = build(data)
    encoded = json.dumps(records, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    compressed = gzip.compress(encoded, mtime=0)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "kr_locations.json.gz").write_bytes(compressed)
    manifest = {"source_url": SOURCE_URL, "source_sha256": hashlib.sha256(data).hexdigest(), "bundle_sha256": hashlib.sha256(compressed).hexdigest(), "generated_at": datetime.now(timezone.utc).isoformat(), "records": len(records), "license": "CC BY 4.0", "attribution": "GeoNames · https://www.geonames.org/", "format_version": 1}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "bytes": len(compressed), "output": str(OUTPUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
