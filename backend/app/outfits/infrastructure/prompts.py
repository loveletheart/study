"""공통·개인화 프롬프트와 날씨·개인 조건 입력 구성."""


# 표준 라이브러리
import json
from dataclasses import asdict

# 프로젝트 모듈
from app.outfits.domain.models import OutfitWeather, Activity, ColdSensitivity, OutfitPreferences, OutfitStyle, ClothingPreference, AvoidItem
from app.outfits.domain.rules import temperature_reference


# 프롬프트 버전
PROMPT_VERSION = "2.2"
PERSONALIZATION_VERSION = "2.5"


# 기본 추천 프롬프트
SYSTEM_PROMPT = """제공된 날씨와 명시한 사용자 요구만 사용해 실용적인 옷차림을 추천하세요. 자연스러운 한국어로 작성하세요.
입력 날짜·개수·순서를 유지하고 output_schema에 맞는 JSON 객체만 반환하세요. Markdown, 추가 필드, 날씨 데이터는 반환하지 마세요.
실제로 흔히 쓰는 의류명을 사용하고 필드마다 한 가지를 선택하세요. 이유는 의류명 안이 아니라 reasons/avoid_reasons에 작성하세요.
separates는 top과 bottom을 채우고 one_piece는 JSON null로 두세요. one_piece는 원피스/점프수트를 채우고 top과 bottom은 JSON null로 두세요.
의류명에 "null", "none", "없음" 같은 자리 채우기 문자열을 쓰지 마세요. 허용된 필드에서만 실제 null을 사용하세요.
outerwear는 상체를 덮는 겉옷, shoes는 신발, accessories는 장갑이나 우산 같은 작은 준비물이며 주요 의류가 아닙니다.
best는 날씨와 사람에게 적합해야 합니다. worst는 실제로 부적절한 별개의 옷차림이어야 합니다.
reasons는 best만, avoid_reasons는 worst만 설명하세요. 각각 짧고 구체적인 문장 1~2개와 유용한 주의사항 0~2개를 작성하세요.
temperature_*는 실제 기온이고 apparent_temperature_*는 체감온도입니다. temperature_labels_ko는 이 사실을 한국어 라벨로 반복합니다.
reference_temperature_c는 temperature_basis에 따른 최고값이며 최저값이나 하루 종일의 온도가 아닙니다. 실제 기온과 체감온도를 구분하세요.
하루 전체 기온 범위, 특히 추운 아침과 야외 노출을 고려하세요. 체감온도에 바람의 냉각 효과를 다시 더하지 마세요.
더위에는 통기성 있는 가벼운 옷을, 추위에는 적절한 보온을 선택하세요. 습도·예보·의류 특성·개인 정보를 지어내지 마세요. 날씨의 null은 0이 아니라 알 수 없음입니다.
look_examples는 필드 구성만 보여줍니다. 현재 날씨와 요청에 맞게 의류를 선택하고 조합과 설명을 자연스럽게 다양하게 작성하세요."""


# 출력 형식 예시
LOOK_EXAMPLES = (
    {"outfit_type": "separates", "top": "셔츠", "bottom": "면바지", "one_piece": None,
     "outerwear": "재킷", "shoes": "운동화", "accessories": ["우산"]},
    {"outfit_type": "one_piece", "top": None, "bottom": None, "one_piece": "면 원피스",
     "outerwear": None, "shoes": "샌들", "accessories": ["모자"]},
)


# 개인화 프롬프트
PERSONALIZATION_INSTRUCTION = """명시된 preferences와 personal_requirements를 모두 함께 반영하세요.
cold_sensitivity='cold'는 추위를 많이 타는 것, 'warm'은 더위를 많이 타는 것, normal은 어느 쪽도 아닌 것을 뜻합니다. 반대로 해석하지 마세요.
formal은 격식 있고 단정한 옷차림, casual은 일상의 편안함, active는 움직임과 땀 관리, outdoor는 야외 노출에 대한 보호가 필요합니다.
실제로 선택한 옷이 이 사람의 요구와 날씨에 어떻게 맞는지 설명하세요. 상투적인 문구를 피하세요.
더위를 탄다고 추운 날 필요한 방한을 생략하지 말고, 추위를 탄다고 더운 날 겨울옷을 정당화하지 마세요."""


# 프롬프트 입력 생성
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


def _personal_requirements(preferences: OutfitPreferences) -> dict[str, str]:
    """선택값의 의미를 모델에 설명하며 사용자에게 보여줄 추천 문장은 만들지 않는다."""
    requirements = {
        "체온_성향": {
            ColdSensitivity.NORMAL: "추위와 더위에 대한 민감도는 보통입니다. 하루의 기온 범위에 맞춰 조절하세요.",
            ColdSensitivity.COLD: "추위를 많이 탑니다. 추운 시간과 야외 활동의 보온·방풍, 노출 감소를 우선 고려하세요.",
            ColdSensitivity.WARM: "더위를 많이 탑니다. 통풍·흡습과 쉽게 벗는 레이어를 고려하되 추운 시간의 방한은 유지하세요.",
        }[preferences.cold_sensitivity],
        "스타일": {
            OutfitStyle.DEFAULT: "특정 스타일을 요구하지 않았습니다. 명시된 날씨와 활동에 맞는 일상복을 구성하세요.",
            OutfitStyle.CASUAL: "편안한 캐주얼 스타일을 원합니다. 움직임이 편하고 일상에서 조화로운 구성을 선택하세요.",
            OutfitStyle.FORMAL: "격식 있고 단정한 스타일을 원합니다. 스포츠웨어 중심의 조합을 피하고 소재와 실루엣을 고려하세요.",
        }[preferences.style],
        "활동": {
            Activity.DAILY: "일상 활동을 할 예정입니다. 특정 직업이나 별도의 운동 계획은 가정하지 마세요.",
            Activity.OUTDOOR: "야외 활동을 할 예정입니다. 외기에 노출되므로 최저 기온·강수·바람과 활동 편의성을 고려하세요.",
            Activity.ACTIVE: "몸을 활발히 움직이는 활동을 할 예정입니다. 신축성·흡습·통풍과 활동 전후 체온 조절을 고려하세요.",
        }[preferences.activity],
    }
    if preferences.clothing_preference != ClothingPreference.ANY:
        requirements["선호_의류"] = {
            ClothingPreference.MENSWEAR: "남성복 위주의 의류와 실루엣을 선호합니다. 성별 정체성이나 신체 치수는 추정하지 마세요.",
            ClothingPreference.WOMENSWEAR: "여성복 위주의 의류와 실루엣을 선호합니다. 원피스나 치마를 반드시 선택할 필요는 없으며 신체 치수는 추정하지 마세요.",
        }[preferences.clothing_preference]
    if preferences.avoid_items:
        names = {AvoidItem.SKIRTS: "치마", AvoidItem.DRESSES: "원피스", AvoidItem.SHORTS: "반바지", AvoidItem.SANDALS: "샌들", AvoidItem.HEELS: "굽 높은 신발", AvoidItem.SLEEVELESS: "민소매"}
        requirements["피할_의류"] = "베스트 추천에서 다음 항목을 제외하세요: " + ", ".join(names[item] for item in preferences.avoid_items) + ". 날씨에 맞는 대안을 선택하고 피하는 이유나 개인 사정을 지어내지 마세요."
    return requirements
