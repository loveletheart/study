"""로컬 모델이 생성해야 하는 최소 JSON 구조."""

from datetime import date as Date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.outfits.domain.models import OutfitType, validate_clothing_name, validate_outfit_parts

ClothingText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200), AfterValidator(validate_clothing_name)]
ExplanationText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class GeneratedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeneratedLook(GeneratedModel):
    outfit_type: OutfitType = Field(description="separates: top and bottom; one_piece: a dress or jumpsuit")
    top: ClothingText | None = Field(description="One upper-body garment. Null for one_piece outfits")
    bottom: ClothingText | None = Field(description="One lower-body garment. Null for one_piece outfits")
    one_piece: ClothingText | None = Field(description="Dress or jumpsuit. Null for separates outfits")
    outerwear: ClothingText | None = Field(description="Upper-body outer layer, such as a jacket. Null when unnecessary")
    shoes: ClothingText = Field(description="Footwear only; never gloves or other accessories")
    accessories: list[ClothingText] = Field(max_length=10, description="Small accessories or umbrella; no main garments")

    @model_validator(mode="after")
    def check_parts(self) -> "GeneratedLook":
        validate_outfit_parts(self.outfit_type, self.top, self.bottom, self.one_piece)
        return self


class GeneratedDay(GeneratedModel):
    date: Date
    best: GeneratedLook
    worst: GeneratedLook
    reasons: list[ExplanationText] = Field(min_length=1, max_length=2, description="Why best suits this weather and request")
    avoid_reasons: list[ExplanationText] = Field(min_length=1, max_length=2, description="Why worst is unsuitable; do not mix into reasons")
    precautions: list[ExplanationText] = Field(max_length=2, description="Only actionable weather precautions, or an empty list")


class GeneratedResponse(GeneratedModel):
    days: list[GeneratedDay] = Field(min_length=1, max_length=7)
