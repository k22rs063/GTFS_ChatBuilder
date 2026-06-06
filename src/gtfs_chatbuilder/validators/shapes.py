"""shapes.txt のバリデーション (v4 条件付必須/推奨)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "shape_id",
    "shape_pt_lat",
    "shape_pt_lon",
    "shape_pt_sequence",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: 座標妥当性、shape_pt_sequence の増加性、shape_id ごとの点列の連続性
    return check_basic(workspace, "shapes.txt", REQUIRED_COLUMNS, is_optional=True)
