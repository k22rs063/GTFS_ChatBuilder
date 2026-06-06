"""calendar_dates.txt のバリデーション (v4 条件付必須)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "service_id",
    "date",
    "exception_type",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: exception_type は 1/2、日付フォーマット (YYYYMMDD)
    # 祝日・お盆・年末年始の例外を持つ場合は必須
    return check_basic(
        workspace, "calendar_dates.txt", REQUIRED_COLUMNS, is_optional=True
    )
