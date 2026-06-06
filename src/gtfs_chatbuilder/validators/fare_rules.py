"""fare_rules.txt のバリデーション (v4 条件付必須)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "fare_id",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: fare_id が fare_attributes に存在、origin_id/destination_id が stops.zone_id 参照、
    # route_id が routes に存在。全線均一運賃の場合は不要
    return check_basic(
        workspace, "fare_rules.txt", REQUIRED_COLUMNS, is_optional=True
    )
