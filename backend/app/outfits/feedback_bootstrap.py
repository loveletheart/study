from functools import lru_cache
from pathlib import Path
from app.common.config import get_settings
from app.outfits.infrastructure.feedback import SQLiteFeedbackStore


@lru_cache
def feedback_store_for_path(path: Path) -> SQLiteFeedbackStore:
    return SQLiteFeedbackStore(path)


def get_feedback_store() -> SQLiteFeedbackStore:
    return feedback_store_for_path(get_settings().database_path)
