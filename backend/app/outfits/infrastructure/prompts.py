"""날씨 사실과 옷차림 생성 요청을 분리한 프롬프트."""

import json
from dataclasses import asdict

from app.outfits.domain.models import OutfitWeather
from app.outfits.domain.rules import temperature_reference

PROMPT_VERSION = "2.1"
SYSTEM_PROMPT = """Recommend practical outfits using only the supplied weather and explicit user needs. Write natural Korean.
Return only output_schema's JSON object, preserving input dates, count and order. No markdown, extra fields or weather data.
Use real, commonly used clothing names, one choice per field. Put reasons in reasons/avoid_reasons, not inside garment names.
For separates, provide top and bottom and set one_piece to JSON null. For one_piece, provide a dress/jumpsuit and set top and bottom to JSON null.
Never write placeholder strings such as \"null\", \"none\" or \"없음\" as clothing. Use actual null only where allowed.
Outerwear covers the upper body; shoes are footwear; accessories are small items such as gloves or an umbrella, not main garments.
Best must suit the weather and person. Worst must be a genuinely unsuitable, different outfit.
Reasons explain only best; avoid_reasons explain only worst. Use 1-2 short concrete sentences each and 0-2 useful precautions.
temperature_* are actual temperatures; apparent_temperature_* are feels-like values. temperature_labels_ko repeats these facts with Korean labels.
reference_temperature_c is the maximum for temperature_basis, not the minimum or an all-day temperature. Keep actual and feels-like terms distinct.
Consider the full daily range, especially cold mornings and outdoor exposure. Do not add wind chill again to feels-like values.
Use breathable light clothes in heat and appropriate insulation in cold. Do not invent humidity, forecasts, garment properties or personal facts. Null weather values are unknown, not zero.
look_examples teach field layout only. Choose clothes for the current weather and request; vary combinations and explanations naturally."""

LOOK_EXAMPLES = (
    {"outfit_type": "separates", "top": "셔츠", "bottom": "면바지", "one_piece": None,
     "outerwear": "재킷", "shoes": "운동화", "accessories": ["우산"]},
    {"outfit_type": "one_piece", "top": None, "bottom": None, "one_piece": "면 원피스",
     "outerwear": None, "shoes": "샌들", "accessories": ["모자"]},
)


def build_messages(days: tuple[OutfitWeather, ...], schema: dict) -> list[dict[str, str]]:
    """날씨 원본과 출력 스키마로 채팅 메시지 구성"""
    weather = []
    for day in days:
        basis, reference = temperature_reference(day)
        weather.append({
            **asdict(day), "date": day.date.isoformat(),
            "temperature_basis": basis.value, "reference_temperature_c": reference,
            "temperature_labels_ko": {
                "실제기온_최저_C": day.temperature_min_c, "실제기온_최고_C": day.temperature_max_c,
                "체감온도_최저_C": day.apparent_temperature_min_c, "체감온도_최고_C": day.apparent_temperature_max_c,
            },
        })
    content = json.dumps({
        "timezone": "Asia/Seoul",
        "units": {"temperature": "°C", "precipitation": "mm", "snowfall": "cm", "wind_speed": "m/s", "probability": "%"},
        "weather_days": weather, "unprovided_weather": ["humidity"],
        "look_examples": LOOK_EXAMPLES, "output_schema": schema,
    }, ensure_ascii=False, allow_nan=False)
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]
