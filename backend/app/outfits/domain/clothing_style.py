"""의류명에서 명확히 드러나는 스타일 범주를 판별한다."""

import re
from collections.abc import Iterable
from unicodedata import normalize

from app.outfits.domain.models import AvoidItem, ClothingPreference


_SKIRT = r"스커트|치마|\bskirts?\b"
_DRESS = (
    r"원\s*피스|드레스(?![\s-]*(?:셔츠|슈즈|구두|부츠|신발))"
    r"|\bdress(?:es)?\b(?![\s-]*(?:shirts?|shoes?|boots?))"
)
_HEELS = r"하이[\s-]*힐|스틸레토|\b(?:high[\s-]*heels?|stilettos?)\b"


_MENSWEAR = re.compile(
    r"^남성\s+|남성\s*(?:용|복|전용|의류)|남자\s*(?:용|전용)|\b(?:menswear|men['\u2019]s|for men)\b"
)
_WOMENSWEAR = re.compile(
    r"^여성\s+|여성\s*(?:용|복|전용|의류)|여자\s*(?:용|전용)|\b(?:womenswear|women['\u2019]s|for women)\b"
    rf"|{_DRESS}|{_SKIRT}|{_HEELS}"
)
_OTHER_STYLE = {
    ClothingPreference.MENSWEAR: _WOMENSWEAR,
    ClothingPreference.WOMENSWEAR: _MENSWEAR,
}

_AVOID_OPTIONS = {
    AvoidItem.SKIRTS: ("치마", ("bottom", "one_piece"), _SKIRT),
    AvoidItem.DRESSES: ("원피스", ("one_piece", "top"), _DRESS),
    AvoidItem.SHORTS: ("반바지", ("bottom",), r"반\s*바지|쇼츠|\bshorts\b"),
    AvoidItem.SANDALS: ("샌들", ("shoes",), r"샌들|\bsandals?\b"),
    AvoidItem.HEELS: ("굽 높은 신발", ("shoes",), rf"{_HEELS}|굽(?:이)?\s*높은"),
    AvoidItem.SLEEVELESS: ("민소매", ("top", "one_piece"), r"민\s*소매|나시|슬리브리스|\bsleeveless\b|\btank[\s-]*tops?\b"),
}
AVOID_ITEM_NAMES = {item: option[0] for item, option in _AVOID_OPTIONS.items()}


def _normalized_name(name: str) -> str:
    return normalize("NFKC", name).casefold().replace("앞치마", "")


def conflicting_clothes(look: dict, preference: ClothingPreference | str | None) -> tuple[str, ...]:
    """선택한 스타일과 명확히 충돌하는 품목만 반환한다."""
    pattern = _OTHER_STYLE.get(preference)
    if pattern is None:
        return ()

    names = [look.get(field) for field in ('top', 'bottom', 'one_piece', 'outerwear', 'shoes')]
    names.extend(look.get('accessories') or ())
    return tuple(dict.fromkeys(name for name in names if name and pattern.search(_normalized_name(name))))


def avoided_clothes(look: dict, avoid_items: Iterable[str]) -> tuple[str, ...]:
    """이용자가 피하려는 품목이 해당 의류 칸에 들어갔는지 확인한다."""
    matches = []
    for item in avoid_items:
        if item not in _AVOID_OPTIONS:
            continue
        _, fields, pattern = _AVOID_OPTIONS[item]
        for field in fields:
            name = look.get(field)
            if name and re.search(pattern, _normalized_name(name)):
                matches.append(name)
    return tuple(dict.fromkeys(matches))
