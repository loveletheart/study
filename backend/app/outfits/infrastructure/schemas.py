"""공통·개인화 모델 생성 응답의 검증 스키마."""


# 표준 라이브러리
from datetime import date as Date
from typing import Annotated

# 외부 라이브러리
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

# 프로젝트 모듈
from app.outfits.domain.models import OutfitType, validate_clothing_name, validate_outfit_parts


# 문자열 검증 타입
ClothingText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200), AfterValidator(validate_clothing_name)]
ExplanationText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


# 검증 모델
class GeneratedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeneratedLook(GeneratedModel):
    outfit_type: OutfitType = Field(description="separates: 상의와 하의; one_piece: 원피스 또는 점프수트")
    top: ClothingText | None = Field(description="상의 한 가지. one_piece 구성이면 null")
    bottom: ClothingText | None = Field(description="하의 한 가지. one_piece 구성이면 null")
    one_piece: ClothingText | None = Field(description="원피스 또는 점프수트. separates 구성이면 null")
    outerwear: ClothingText | None = Field(description="재킷처럼 상체에 입는 겉옷. 불필요하면 null")
    shoes: ClothingText = Field(description="신발만 해당하며 장갑이나 다른 액세서리는 불가")
    accessories: list[ClothingText] = Field(max_length=10, description="작은 액세서리 또는 우산. 주요 의류는 불가")

    @model_validator(mode="after")
    def check_parts(self) -> "GeneratedLook":
        validate_outfit_parts(self.outfit_type, self.top, self.bottom, self.one_piece)
        return self


class GeneratedDay(GeneratedModel):
    date: Date
    best: GeneratedLook
    worst: GeneratedLook
    reasons: list[ExplanationText] = Field(min_length=1, max_length=2, description="best가 이 날씨와 요청에 적합한 이유")
    avoid_reasons: list[ExplanationText] = Field(min_length=1, max_length=2, description="worst가 부적절한 이유. reasons에 섞지 않음")
    precautions: list[ExplanationText] = Field(max_length=2, description="실행 가능한 날씨 주의사항만 작성하거나 빈 목록")


class GeneratedResponse(GeneratedModel):
    days: list[GeneratedDay] = Field(min_length=1, max_length=7)
