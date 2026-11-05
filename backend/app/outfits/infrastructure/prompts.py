"""날씨 사실과 옷차림 생성 요청을 분리한 프롬프트."""

import json
from dataclasses import asdict

from app.outfits.domain.models import OutfitWeather
from app.outfits.domain.rules import temperature_reference

PROMPT_VERSION = "1.0"
SYSTEM_PROMPT = """당신은 날씨에 맞는 일상복을 한국어로 제안하는 옷차림 추천자입니다.
제공된 날씨 사실만 사용하고 날짜, 수치와 누락된 정보를 만들어내지 마세요.
날짜별 베스트·워스트 옷차림을 구체적인 상의·하의·겉옷·신발·추가 준비물로 구성하세요.
고정된 기온별 의류 목록에 한정하지 말고 색상·소재·레이어링을 활용해 조화롭게 제안하세요.
낮의 기준 온도뿐 아니라 아침·저녁의 최저 온도, 비·눈·바람·일교차도 함께 고려하세요.
체감온도가 있으면 바람 때문에 체감온도를 다시 낮추는 계산은 하지 마세요.
강수확률은 강수가 확정됐다는 뜻이 아니며 null은 0이나 맑음을 뜻하지 않습니다.
개인의 성별·보유 의류·활동·취향이나 실제 인기 순위를 임의로 가정하지 마세요.
베스트와 워스트는 서로 다른 구성으로 제안하고 각각의 이유를 설명하세요.
겉옷이 필요 없으면 outerwear는 null, 준비물이 없으면 accessories는 빈 배열입니다.
입력과 같은 날짜·개수·순서를 유지하고 아래 JSON 스키마에 맞는 객체만 반환하세요.
날씨 자체와 추가 필드는 반환하지 말고 Markdown이나 코드 블록도 사용하지 마세요."""


def build_messages(days: tuple[OutfitWeather, ...], schema: dict) -> list[dict[str, str]]:
    """날씨 원본과 출력 스키마로 채팅 메시지 구성"""
    weather = []
    for day in days:
        basis, reference = temperature_reference(day)
        weather.append({
            **asdict(day), "date": day.date.isoformat(),
            "temperature_basis": basis.value, "reference_temperature_c": reference,
        })
    content = json.dumps({
        "timezone": "Asia/Seoul",
        "units": {"temperature": "°C", "precipitation": "mm", "snowfall": "cm", "wind_speed": "m/s", "probability": "%"},
        "weather_days": weather, "output_schema": schema,
    }, ensure_ascii=False, allow_nan=False)
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]
