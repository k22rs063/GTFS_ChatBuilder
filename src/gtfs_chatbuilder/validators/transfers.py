"""transfers.txt のバリデーション (v4 推奨)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult, check_basic

REQUIRED_COLUMNS = [
    "transfer_type",
]


def validate(workspace: Path) -> ValidationResult:
    # TODO: transfer_type=0-5、from_stop_id/to_stop_id が stops.txt に存在、
    # transfer_type=2 のとき min_transfer_time 必須
    return check_basic(
        workspace, "transfers.txt", REQUIRED_COLUMNS, is_optional=True
    )
