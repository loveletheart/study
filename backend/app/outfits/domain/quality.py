import re
from dataclasses import dataclass

from app.outfits.domain.clothing_style import conflicting_clothes


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


def check_day(day: dict, weather: dict, preferences: dict | None = None) -> dict:
    errors, warnings = training_text_issues(day), []
    clothing_preference = (preferences or {}).get('clothing_preference')
    for label in ('best', 'worst'):
        outfit = day[label]
        if conflicts := conflicting_clothes(outfit, clothing_preference):
            errors.append(QualityIssue(
                'clothing_preference',
                f"{label} 조합에서 선택한 의류 유형과 맞지 않는 품목({', '.join(conflicts)})을 빼고 계절에 맞는 대안으로 바꿔 주세요.",
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
    apparent = weather.get('apparent_temperature_min_c') is not None and weather.get('apparent_temperature_max_c') is not None
    low = weather.get('apparent_temperature_min_c') if apparent else weather.get('temperature_min_c')
    explanation = ' '.join(day.get('reasons', []) + day.get('avoid_reasons', []) + day.get('precautions', []))
    if low is not None and low >= 27 and re.search(r'(?:2[7-9]|[3-5]\d)(?:\.\d+)?\s*(?:도|°C|℃).{0,10}(?:너무 추|추위|추운)', explanation):
        errors.append(QualityIssue('weather_logic', '높은 기온을 추위의 근거로 설명하고 있습니다.'))
    if re.search('플라스틱 원피스|고무장갑.{0,12}(?:부츠|방한화)|발이 썩', explanation + str(day['best']) + str(day['worst'])):
        errors.append(QualityIssue('clothing_category', '현실적인 의류명과 확인 가능한 설명을 사용해 주세요.'))
    if weather.get('precipitation_mm') is None and weather.get('precipitation_probability_percent') is None and re.search('비가 오지 않|우산.{0,8}(?:필요 없|필요하지 않)', explanation):
        errors.append(QualityIssue('weather_logic', '강수 정보가 없으면 비가 오지 않는다고 단정할 수 없습니다.'))
    if re.search('습도.{0,8}(?:높|낮)|고온다습', explanation):
        warnings.append(QualityIssue('unsupported_weather', '습도 자료가 없는 상태에서 습도를 단정했는지 확인해 주세요.'))
    if day['best']['outfit_type'] == 'one_piece' and re.search('상의와 하의.{0,10}(?:선택|고릅|구성)', ' '.join(day.get('reasons', []))):
        warnings.append(QualityIssue('explanation_mismatch', '선택한 원피스와 추천 이유가 서로 맞는지 확인해 주세요.'))
    return {'errors': [issue.__dict__ for issue in dict.fromkeys(errors)], 'warnings': [issue.__dict__ for issue in dict.fromkeys(warnings)]}
