"""stops.txt のバリデーション (v4 必須ファイル)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import (
    ValidationResult,
    check_basic,
    read_csv_records,
)

REQUIRED_COLUMNS = [
    "stop_id",
    "stop_name",
    "stop_lat",
    "stop_lon",
    "location_type",
]


def validate(workspace: Path) -> ValidationResult:
    result = check_basic(workspace, "stops.txt", REQUIRED_COLUMNS)
    if result.status != "completed":
        return result

    # 詳細チェック: location_type=0/空 の停留所 (乗り場) は座標が必須。
    # Phase 1 は location_type=0 のみ。座標が空の停留所を in_progress として検出する。
    records = read_csv_records(workspace / "stops.txt")
    missing_coord: list[str] = []
    invalid_coord: list[str] = []

    for rec in records:
        location_type = (rec.get("location_type") or "").strip()
        # location_type が 0 または空のときのみ座標必須 (v4 仕様)
        if location_type not in ("", "0"):
            continue
        name = (rec.get("stop_name") or "").strip() or "(名称未設定)"
        lat = (rec.get("stop_lat") or "").strip()
        lon = (rec.get("stop_lon") or "").strip()
        if not lat or not lon:
            missing_coord.append(name)
            continue
        if not _is_valid_coordinate(lat, lon):
            invalid_coord.append(name)

    if invalid_coord:
        preview = "、".join(invalid_coord[:5])
        result.status = "error"
        result.blockers.append(
            f"stops.txt: 座標の値が不正な停留所が {len(invalid_coord)}件: {preview}"
        )

    if missing_coord:
        preview = "、".join(missing_coord[:5])
        more = "" if len(missing_coord) <= 5 else " 他"
        # 座標欠落は zip化を阻む blocker (経路検索に必須)
        result.blockers.append(
            f"stops.txt: 座標(stop_lat/stop_lon)が未設定の停留所が "
            f"{len(missing_coord)}件: {preview}{more}"
        )
        if result.status != "error":
            result.status = "in_progress"
        result.fields_missing.append(
            f"{len(missing_coord)}件の座標(stop_lat/stop_lon)"
        )

    return result


def _is_valid_coordinate(lat: str, lon: str) -> bool:
    """緯度・経度が日本国内として妥当な数値かを大まかに判定する。"""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except ValueError:
        return False
    # 日本のおおよその範囲 (沖縄〜北海道、離島含めやや広め)
    return 20.0 <= lat_f <= 46.0 and 122.0 <= lon_f <= 154.0
