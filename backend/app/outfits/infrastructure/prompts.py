"""공통·개인화 프롬프트와 날씨·개인 조건 입력 구성."""


# 표준 라이브러리
import json
from dataclasses import asdict

# 프로젝트 모듈
from app.outfits.domain.clothing_style import AVOID_ITEM_NAMES
from app.outfits.domain.models import OutfitWeather, Activity, AvoidItem, ColdSensitivity, OutfitPreferences, OutfitStyle, ClothingPreference
from app.outfits.domain.rules import temperature_reference


# 프롬프트 버전
PROMPT_VERSION = "2.4"
PERSONALIZATION_VERSION = "2.9"


# 기본 추천 프롬프트
SYSTEM_PROMPT = """제공된 날씨와 명시한 사용자 요구만 사용해 실용적인 옷차림을 추천하세요. 자연스러운 한국어로 작성하세요.
입력 날짜·개수·순서를 유지하고 output_schema에 맞는 JSON 객체만 반환하세요. Markdown, 추가 필드, 날씨 데이터는 반환하지 마세요.
실제로 흔히 쓰는 의류명을 사용하고 필드마다 한 가지를 선택하세요. 이유는 의류명 안이 아니라 reasons/avoid_reasons에 작성하세요.
모든 날짜의 best와 worst에서 값이 있는 top, bottom, outerwear, one_piece의 이름에 대표 바탕색과 눈에 보이는 디자인 특징을 함께 쓰세요.
검정, 흰색, 네이비, 베이지, 아이보리, 차콜, 회색, 카키, 하늘색, 파랑, 초록, 버건디, 빨강, 분홍, 갈색, 노랑 중 하나를 사용하세요.
상의와 원피스·점프수트는 의류에 맞는 네크라인이나 칼라를 하나 고르고 반팔·긴팔·민소매처럼 소매 형태도 적으세요.
- 크루넥(라운드넥)은 둥근 목선, 브이넥은 V자 목선입니다.
- 터틀넥(목폴라)은 목을 감싸고, 모크넥은 목선이 살짝 올라옵니다.
- 오프숄더는 어깨를 드러내고, 보트넥은 쇄골을 따라 넓게 이어지며, 스퀘어넥은 각진 목선입니다.
- 칼라(카라)가 있는 옷은 셔츠 칼라, 폴로 칼라, 스탠드 칼라처럼 구체적인 이름을 쓰세요.
하의는 일자핏·와이드핏·테이퍼드핏, 투턱·플리츠·플레어처럼 핏이나 디테일을 고르고 긴바지·반바지·미디 스커트처럼 기장을 드러내세요.
겉옷은 싱글버튼·더블버튼·지퍼 여밈·벨트형처럼 실제 디자인을 구체적으로 쓰세요. 원피스에는 플레어·셔츠형처럼 어울리는 실루엣을 더할 수 있습니다.
줄무늬나 체크가 어울리면 의류명에 넣고, 무늬 없는 조합도 허용합니다. 신발과 준비물에는 로우컷 운동화, 접이식 우산처럼 구체적인 형태를 쓰세요.
색상과 디자인은 기존 의류명 필드 안에 쓰고 별도 필드를 추가하지 마세요.
separates는 top과 bottom을 채우고 one_piece는 JSON null로 두세요. one_piece는 원피스/점프수트를 채우고 top과 bottom은 JSON null로 두세요.
의류명에 "null", "none", "없음" 같은 자리 채우기 문자열을 쓰지 마세요. 허용된 필드에서만 실제 null을 사용하세요.
outerwear는 상체를 덮는 겉옷, shoes는 신발, accessories는 장갑이나 우산 같은 작은 준비물이며 주요 의류가 아닙니다.
best는 날씨와 사람에게 적합해야 합니다. worst는 색상만 바꾼 조합을 피하고, 날씨나 활동에 실제로 부적절한 별개의 옷차림을 고르세요.
reasons는 best만, avoid_reasons는 worst만 설명하세요. 각각 짧고 구체적인 문장 1~2개와 유용한 주의사항 0~2개를 작성하세요.
temperature_*는 실제 기온이고 apparent_temperature_*는 체감온도입니다. temperature_labels_ko는 이 사실을 한국어 라벨로 반복합니다.
reference_temperature_c는 temperature_basis에 따른 최고값이며 최저값이나 하루 종일의 온도가 아닙니다. 실제 기온과 체감온도를 구분하세요.
하루 전체 기온 범위, 특히 추운 아침과 야외 노출을 고려하세요. 체감온도에 바람의 냉각 효과를 다시 더하지 마세요.
더위에는 통기성 있는 가벼운 옷을, 추위에는 적절한 보온을 선택하세요. 습도·예보·의류 특성·개인 정보를 지어내지 마세요. 날씨의 null은 0이 아니라 알 수 없음입니다.
look_examples는 필드 구성과 이름의 작성 방식 예시입니다. 현재 날씨와 요청에 맞게 의류를 선택하고 조합과 설명을 자연스럽게 다양하게 작성하세요."""


# 출력 형식 예시
LOOK_EXAMPLES = (
    {"outfit_type": "separates", "top": "네이비 줄무늬 크루넥 긴팔 티셔츠", "bottom": "베이지 투턱 일자핏 긴바지", "one_piece": None,
     "outerwear": "카키 싱글버튼 트렌치코트", "shoes": "흰색 로우컷 운동화", "accessories": ["검정 접이식 우산"]},
    {"outfit_type": "one_piece", "top": None, "bottom": None, "one_piece": "검정 체크 스퀘어넥 긴팔 플레어 원피스",
     "outerwear": None, "shoes": "갈색 스트랩 샌들", "accessories": ["아이보리 버킷햇"]},
)


# 개인화 프롬프트
PERSONALIZATION_INSTRUCTION = """옷을 고르기 전에 preferences와 personal_requirements를 확인하세요.
best와 worst를 모두 선택한 의류 스타일과 공용 의류 안에서 구성하세요. 같은 의류 취향 안에서 날씨나 활동에 맞지 않는 조합을 worst로 고르세요.
worst에도 실제로 흔히 입는 옷을 사용하세요. 예를 들어 더운 날에는 두꺼운 니트와 무거운 바지 조합을 피할 옷차림으로 보여 줄 수 있습니다.
best에서는 피할 의류를 모두 제외하고 날씨와 활동에 맞는 대안을 사용하세요.
temperature_basis가 temperature이면 실제 기온, apparent_temperature이면 체감온도를 근거로 삼으세요. 제공되지 않은 체감온도나 시간대별 바람은 추정하지 마세요.
최저기온도 높은 날에는 아침 방한이나 한낮 겉옷을 관성적으로 권하지 마세요. 필요 없으면 outerwear를 null로 두세요.
의류의 방수 등 기능은 의류명에 그 기능을 명시한 경우에만 근거로 쓰세요.
각 설명은 실제 옷과 날씨를 연결하는 짧은 문장으로 작성하세요. 별도 주의사항이 없으면 precautions는 빈 목록으로 두세요.
의류 선호로 성별 정체성이나 치수를 추정하지 마세요."""


_AVOID_ALTERNATIVES = {
    AvoidItem.SKIRTS: "하의는 바지를 고르세요.",
    AvoidItem.DRESSES: "상의와 하의를 조합하거나 날씨에 맞는 점프수트를 고를 수 있습니다.",
    AvoidItem.SHORTS: "하의는 긴 바지를 고르세요.",
    AvoidItem.SANDALS: "신발은 활동에 맞는 닫힌 신발을 고르세요.",
    AvoidItem.HEELS: "신발은 굽이 낮은 것을 고르세요.",
    AvoidItem.SLEEVELESS: "상의는 반팔 티셔츠나 소매가 있는 셔츠처럼 소매 있는 옷을 고르세요.",
}


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
    payload = {
        "timezone": "Asia/Seoul",
        "units": {"temperature": "°C", "precipitation": "mm", "snowfall": "cm", "wind_speed": "m/s", "probability": "%"},
        "weather_days": weather, "unprovided_weather": ["humidity"],
        "look_examples": LOOK_EXAMPLES, "output_schema": schema,
    }
    if any((day.precipitation_mm or 0) > 0 or (day.precipitation_probability_percent or 0) > 0 for day in days):
        payload["rain_protection"] = (
            "비에 대비하는 날에는 우산, 우비, 장화 또는 이름에 방수 기능을 명시한 품목이 비를 막는 역할을 설명하세요. "
            "일반 코트나 운동화를 고르면 보온이나 걷기 편한 점을 설명하세요. "
            "비를 막는 품목과 따뜻하게 입는 옷을 각각 구체적으로 설명하세요."
        )
    content = json.dumps(payload, ensure_ascii=False, allow_nan=False)
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
            ClothingPreference.MENSWEAR: (
                "best와 worst 모두 남성복 또는 공용 의류를 고르세요. 원피스·드레스·치마·하이힐은 제외하세요. "
                "상의와 하의가 있는 조합은 separates입니다. 남성용 또는 공용 점프수트를 고른 경우에만 one_piece를 쓰세요."
            ),
            ClothingPreference.WOMENSWEAR: (
                "best와 worst 모두 여성복 또는 공용 의류를 고르세요. 남성 전용 품목은 제외하세요. "
                "상의와 바지 조합, 치마, 원피스, 점프수트를 날씨와 활동에 맞게 선택할 수 있습니다."
            ),
        }[preferences.clothing_preference]
    if preferences.avoid_items:
        names = ", ".join(AVOID_ITEM_NAMES[item] for item in preferences.avoid_items)
        alternatives = " ".join(_AVOID_ALTERNATIVES[item] for item in preferences.avoid_items)
        requirements["피할_의류"] = f"best 제외 품목은 {names}입니다. best에는 다음 대안을 사용하세요. {alternatives}"
    return requirements
