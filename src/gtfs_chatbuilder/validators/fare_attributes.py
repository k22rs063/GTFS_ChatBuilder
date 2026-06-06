"""fare_attributes.txt のバリデーション (v4 必須ファイル)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "fare_id",
    "price",
    "currency_type",
    "payment_method",
    "transfers",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: currency_type="JPY"、payment_method 0/1、transfers 0/1/2/空
    # 無料サービスでも price=0 で必須
    return check_basic(workspace, "fare_attributes.txt", REQUIRED_COLUMNS)
