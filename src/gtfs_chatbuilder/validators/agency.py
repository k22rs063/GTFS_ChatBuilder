"""agency.txt のバリデーション (v4 必須ファイル)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "agency_id",
    "agency_name",
    "agency_url",
    "agency_timezone",
    "agency_lang",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: agency_timezone="Asia/Tokyo", agency_lang="ja", URL妥当性等の詳細
    return check_basic(workspace, "agency.txt", REQUIRED_COLUMNS)
