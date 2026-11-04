"""로컬 모델이 생성해야 하는 최소 JSON 구조."""

from datetime import date as Date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ClothingText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ExplanationText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class GeneratedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeneratedLook(GeneratedModel):
    top: ClothingText
    bottom: ClothingText
    outerwear: ClothingText | None
    shoes: ClothingText
    accessories: list[ClothingText] = Field(max_length=10)


class GeneratedDay(GeneratedModel):
    date: Date
    best: GeneratedLook
    worst: GeneratedLook
    reasons: list[ExplanationText] = Field(min_length=1, max_length=6)
    avoid_reasons: list[ExplanationText] = Field(min_length=1, max_length=6)
    precautions: list[ExplanationText] = Field(max_length=8)


class GeneratedResponse(GeneratedModel):
    days: list[GeneratedDay] = Field(min_length=1, max_length=7)
