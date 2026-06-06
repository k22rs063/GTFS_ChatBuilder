"""feed_info.txt のバリデーション (v4 必須ファイル)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "feed_publisher_name",
    "feed_publisher_url",
    "feed_lang",
    "feed_start_date",
    "feed_end_date",
    "feed_version",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: 日付フォーマット (YYYYMMDD) チェック、feed_lang が "ja" か等の詳細
    return check_basic(workspace, "feed_info.txt", REQUIRED_COLUMNS)
