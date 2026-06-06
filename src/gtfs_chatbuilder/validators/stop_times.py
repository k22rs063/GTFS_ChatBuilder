"""stop_times.txt のバリデーション (v4 必須ファイル)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "trip_id",
    "arrival_time",
    "departure_time",
    "stop_id",
    "stop_sequence",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: trip_id が trips.txt に存在、stop_id が stops.txt に存在、
    # 時刻フォーマット (HH:MM:SS, 24時以降可)、stop_sequence の増加性
    # ★既存 stopTimesProcessor.mjs の stop_id 結合バグの検知もここで
    return check_basic(workspace, "stop_times.txt", REQUIRED_COLUMNS)
