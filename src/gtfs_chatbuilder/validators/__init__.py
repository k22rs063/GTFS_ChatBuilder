"""GTFS-JP v4 ファイル群のバリデータ。

設計指針: design_validation.md
- 緩いモード (ツール呼び出し時は警告のみ)
- get_project_status 経由で随時呼ばれる
- Phase 1 は Python専用バリデータのみ (MobilityData 公式 validator は Phase 2)

Phase 1 の各 validator はスケルトン実装:
- ファイル存在の有無
- 存在すれば必須列の有無 + 行数
- 詳細フィールドチェックは TODO で残す
"""

from __future__ import annotations

from pathlib import Path

from gtfs_chatbuilder.validators.base import ValidationResult
from gtfs_chatbuilder.validators import (
    agency,
    attributions,
    calendar,
    calendar_dates,
    fare_attributes,
    fare_rules,
    feed_info,
    routes,
    shapes,
    stops,
    stop_times,
    transfers,
    translations,
    trips,
)

VALIDATORS = {
    "feed_info": feed_info.validate,
    "agency": agency.validate,
    "stops": stops.validate,
    "translations": translations.validate,
    "routes": routes.validate,
    "trips": trips.validate,
    "stop_times": stop_times.validate,
    "calendar": calendar.validate,
    "calendar_dates": calendar_dates.validate,
    "fare_attributes": fare_attributes.validate,
    "fare_rules": fare_rules.validate,
    "shapes": shapes.validate,
    "attributions": attributions.validate,
    "transfers": transfers.validate,
}


def validate_all(workspace: Path) -> dict[str, ValidationResult]:
    """全ステップのバリデーションを実行して結果を返す。"""
    return {name: fn(workspace) for name, fn in VALIDATORS.items()}


__all__ = ["ValidationResult", "VALIDATORS", "validate_all"]
