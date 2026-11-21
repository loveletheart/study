import re
from dataclasses import dataclass

from app.outfits.domain.clothing_style import avoided_clothes, conflicting_clothes


HOT_DAY_MINIMUM_C = 27
_RAIN_GEAR = re.compile(r'우산|우비|장화|레인\s*(?:코트|부츠|재킷|자켓)')
_WATER_PROTECTION = re.compile(r'방수|발수|\bwaterproof\b', re.IGNORECASE)
_RAIN_PROTECTION_CLAIM = re.compile(
    r'(?:비를|비와\s*바람을|비바람을)\s*(?:(?:효과적으로|잘)\s*)?'
    r'(?:막(?:아|고|으며|습니다)|(?:차단|방지)(?:해|하고|하며|합니다))'
    r'|비에\s*젖지\s*않도록\s*보호(?:해|하고|하며|하면서|합니다)'
)
_NEGATED_PROTECTION = re.compile(r'(?:막아|차단해|방지해|보호해)\s*(?:주지|줄\s*수\s*없)')


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str


def training_text_issues(value) -> list[QualityIssue]:
    errors = []
    rendered = str(value)
    if re.search(r'<\|(?:im_start|im_end|endoftext)|</?think>|</?tool_call>', rendered):
        errors.append(QualityIssue('training_control_token', '수정 정답에는 대화 제어 토큰이나 도구 호출을 넣을 수 없습니다.'))
    if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|01[016789][- ]?\d{3,4}[- ]?\d{4}', rendered):
        errors.append(QualityIssue('personal_information', '학습용 정답에서 이메일·전화번호 같은 개인 정보를 제거해 주세요.'))
    return errors


def _unsupported_rain_protection(explanations: list[str], look: dict) -> bool:
    """선택한 일반 의류에 직접 연결한 강수 차단 설명을 검사한다."""
    names = tuple(
        name for key in ('top', 'bottom', 'one_piece', 'outerwear', 'shoes')
        if (name := look.get(key))
    ) + tuple(look.get('accessories') or ())
    clauses = re.split(r'[,;\n]|(?<=[.!?])\s+', '\n'.join(explanations))
    for clause in clauses:
        claim = _RAIN_PROTECTION_CLAIM.search(clause)
        if claim is None or _NEGATED_PROTECTION.search(clause):
            continue
        subject = clause[:claim.start()]
        if _RAIN_GEAR.search(subject):
            continue
        mentioned = [name for name in names if name in subject]
        if mentioned and not any(_WATER_PROTECTION.search(name) for name in mentioned):
            return True
    return False


def check_day(day: dict, weather: dict, preferences: dict | None = None) -> dict:
    errors, warnings = training_text_issues(day), []
    clothing_preference = (preferences or {}).get('clothing_preference')
    if avoided := avoided_clothes(day['best'], (preferences or {}).get('avoid_items') or ()):
        errors.append(QualityIssue(
            'avoid_items',
            f"best 조합에서 제외 요청한 품목({', '.join(avoided)})을 다른 의류로 바꿔 주세요.",
        ))
    for label in ('best', 'worst'):
        outfit = day[label]
        if conflicts := conflicting_clothes(outfit, clothing_preference):
            errors.append(QualityIssue(
                'clothing_preference',
                f"{label} 조합에 의류 선호와 충돌하는 품목({', '.join(conflicts)})이 있습니다. "
                f"선택한 의류 스타일이나 공용 의류로 같은 역할의 {label} 조합을 다시 작성해 주세요.",
            ))
        if re.search('장갑|우산|목도리|선글라스', outfit.get('shoes') or ''):
            errors.append(QualityIssue('clothing_category', f'{label}의 신발에는 신발만 넣어 주세요.'))
        if re.search('장갑|우산|목도리|선글라스', outfit.get('outerwear') or ''):
            errors.append(QualityIssue('clothing_category', f'{label}의 겉옷에 액세서리가 들어 있습니다.'))
        bottom = outfit.get('bottom') or ''
        if bottom and re.search('상의|티셔츠|니트|재킷|점퍼', bottom) and not re.search('바지|팬츠|슬랙스|스커트|치마', bottom):
            errors.append(QualityIssue('clothing_category', f'{label}의 하의에 상의가 들어 있습니다.'))
        if outfit.get('outfit_type') == 'one_piece' and not re.search('원피스|드레스|점프수트', outfit.get('one_piece') or ''):
            errors.append(QualityIssue('clothing_category', f'{label}의 원피스 항목에는 원피스·드레스·점프수트만 넣어 주세요.'))
        names = ' '.join(str(value) for value in outfit.values())
        if re.search('반팔.{0,3}긴팔|반팔.{0,3}긴소매|긴팔.{0,3}반팔', names):
            errors.append(QualityIssue('clothing_category', f'{label}의 의류명에 서로 다른 소매 길이가 섞여 있습니다.'))
    for field in ('reasons', 'avoid_reasons', 'precautions'):
        entries = day.get(field, [])
        if len(entries) != len(set(entry.strip() for entry in entries)):
            errors.append(QualityIssue('repetition', '같은 설명이 여러 번 반복됩니다.'))
        for entry in entries:
            normalized = re.sub(r'\s+', ' ', entry)
            if re.search(r'(.{16,100}?)\1{2,}', normalized):
                errors.append(QualityIssue('repetition', '설명 안에서 같은 문구가 길게 반복됩니다.'))
    for look, field in (('best', 'reasons'), ('worst', 'avoid_reasons')):
        if _unsupported_rain_protection(day.get(field, []), day[look]):
            errors.append(QualityIssue(
                'weather_logic',
                f"{look}의 설명은 선택한 의류의 실제 역할에 맞게 작성해 주세요. "
                "비를 막는 역할은 우산·우비·장화 또는 방수 기능을 명시한 품목에만 연결해 주세요.",
            ))
    apparent = weather.get('apparent_temperature_min_c') is not None and weather.get('apparent_temperature_max_c') is not None
    low = weather.get('apparent_temperature_min_c') if apparent else weather.get('temperature_min_c')
    explanation = ' '.join(day.get('reasons', []) + day.get('avoid_reasons', []) + day.get('precautions', []))
    if low is not None and low >= HOT_DAY_MINIMUM_C and re.search(r'(?:2[7-9]|[3-5]\d)(?:\.\d+)?\s*(?:도|°C|℃).{0,10}(?:너무 추|추위|추운)', explanation):
        errors.append(QualityIssue('weather_logic', '높은 기온을 추위의 근거로 설명하고 있습니다.'))
    reasons = ' '.join(day.get('reasons', []) + day.get('avoid_reasons', []))
    if (
        preferences is not None and low is not None and low >= HOT_DAY_MINIMUM_C
        and weather.get('apparent_temperature_min_c') is None
        and weather.get('apparent_temperature_max_c') is None
        and re.search(r'낮은\s+체감\s*온도(?:와|에|로|를)', reasons)
    ):
        errors.append(QualityIssue(
            'weather_logic',
            f"체감온도는 제공되지 않았습니다. 실제 최저 {low:g}°C와 실제 최고기온을 근거로 추천과 이유를 작성해 주세요.",
        ))
    if re.search('플라스틱 원피스|고무장갑.{0,12}(?:부츠|방한화)|발이 썩', explanation + str(day['best']) + str(day['worst'])):
        errors.append(QualityIssue('clothing_category', '현실적인 의류명과 확인 가능한 설명을 사용해 주세요.'))
    if weather.get('precipitation_mm') is None and weather.get('precipitation_probability_percent') is None and re.search('비가 오지 않|우산.{0,8}(?:필요 없|필요하지 않)', explanation):
        errors.append(QualityIssue('weather_logic', '강수 정보가 없으면 비가 오지 않는다고 단정할 수 없습니다.'))
    if re.search('습도.{0,8}(?:높|낮)|고온다습', explanation):
        warnings.append(QualityIssue('unsupported_weather', '습도 자료가 없는 상태에서 습도를 단정했는지 확인해 주세요.'))
    if day['best']['outfit_type'] == 'one_piece' and re.search('상의와 하의.{0,10}(?:선택|고릅|구성)', ' '.join(day.get('reasons', []))):
        warnings.append(QualityIssue('explanation_mismatch', '선택한 원피스와 추천 이유가 서로 맞는지 확인해 주세요.'))
    return {'errors': [issue.__dict__ for issue in dict.fromkeys(errors)], 'warnings': [issue.__dict__ for issue in dict.fromkeys(warnings)]}
