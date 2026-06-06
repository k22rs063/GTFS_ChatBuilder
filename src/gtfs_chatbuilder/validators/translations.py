"""translations.txt のバリデーション (v4 必須ファイル)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "table_name",
    "field_name",
    "language",
    "translation",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: 読み仮名 (language=ja-Hrkt) が stops.stop_name 全件を網羅しているか、
    # auto_generated vs user_confirmed のフラグチェック (design_translations.md)
    return check_basic(workspace, "translations.txt", REQUIRED_COLUMNS)
