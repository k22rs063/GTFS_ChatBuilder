"""calendar.txt のバリデーション (v4 条件付必須)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "service_id",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "start_date",
    "end_date",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: 曜日カラムは 0/1、日付フォーマット (YYYYMMDD)
    # 全運行日を calendar_dates.txt のみで表現する場合は不要
    return check_basic(workspace, "calendar.txt", REQUIRED_COLUMNS)
