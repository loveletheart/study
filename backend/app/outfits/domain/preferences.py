"""개인 맞춤 생성에 전달할 사용자 선택 조건."""

from dataclasses import dataclass
from enum import Enum

class ColdSensitivity(str, Enum):
    NORMAL = "normal"
    COLD = "cold"
    WARM = "warm"


class OutfitStyle(str, Enum):
    DEFAULT = "default"
    CASUAL = "casual"
    FORMAL = "formal"


class Activity(str, Enum):
    DAILY = "daily"
    OUTDOOR = "outdoor"
    ACTIVE = "active"


@dataclass(frozen=True)
class OutfitPreferences:
    cold_sensitivity: ColdSensitivity = ColdSensitivity.NORMAL
    style: OutfitStyle = OutfitStyle.DEFAULT
    activity: Activity = Activity.DAILY
