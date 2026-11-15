"""의류명에서 명확히 드러나는 스타일 범주를 판별한다."""

import re
from unicodedata import normalize

from app.outfits.domain.models import ClothingPreference


_MENSWEAR = re.compile(
    r"^남성\s+|남성\s*(?:용|복|전용|의류)|남자\s*(?:용|전용)|\b(?:menswear|men['\u2019]s|for men)\b"
)
_WOMENSWEAR = re.compile(
    r"^여성\s+|여성\s*(?:용|복|전용|의류)|여자\s*(?:용|전용)|\b(?:womenswear|women['\u2019]s|for women)\b"
    r"|원피스|스커트|치마|하이힐|스틸레토"
    r"|드레스(?![\s-]*(?:셔츠|슈즈|구두|부츠|신발))"
    r"|\bdress(?:es)?\b(?![\s-]*(?:shirts?|shoes?|boots?))|\bskirts?\b"
)
_OTHER_STYLE = {
    ClothingPreference.MENSWEAR: _WOMENSWEAR,
    ClothingPreference.WOMENSWEAR: _MENSWEAR,
}


def conflicting_clothes(look: dict, preference: ClothingPreference | str | None) -> tuple[str, ...]:
    """선택한 스타일과 명확히 충돌하는 품목만 반환한다."""
    pattern = _OTHER_STYLE.get(preference)
    if pattern is None:
        return ()

    names = [look.get(field) for field in ('top', 'bottom', 'one_piece', 'outerwear', 'shoes')]
    names.extend(look.get('accessories') or ())
    conflicts = []
    for name in names:
        if name:
            normalized = normalize('NFKC', name).casefold().replace('앞치마', '')
            if pattern.search(normalized):
                conflicts.append(name)
    return tuple(dict.fromkeys(conflicts))
