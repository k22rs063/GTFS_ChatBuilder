"""attributions.txt のバリデーション (v4 推奨)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "organization_name",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: is_producer/is_operator/is_authority のいずれか1つは 1 が必須、
    # agency_id/route_id/trip_id は同時に1つだけ
    return check_basic(
        workspace, "attributions.txt", REQUIRED_COLUMNS, is_optional=True
    )
