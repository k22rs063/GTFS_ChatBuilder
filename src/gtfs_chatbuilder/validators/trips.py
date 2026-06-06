"""trips.txt のバリデーション (v4 必須ファイル)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "route_id",
    "service_id",
    "trip_id",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: route_id が routes.txt に存在、service_id が calendar/calendar_dates に存在、
    # trip_headsign 推奨、direction_id 推奨
    return check_basic(workspace, "trips.txt", REQUIRED_COLUMNS)
