"""routes.txt のバリデーション (v4 必須ファイル)。"""

from pathlib import Path

from gtfs_chatbuilder.validators.base import (
    ValidationResult,
    check_basic,
    read_csv_records,
)

REQUIRED_COLUMNS = [
    "route_id",
    "agency_id",
    "route_type",
]

# v4 で有効な route_type の値
_VALID_ROUTE_TYPES = {"0", "1", "2", "3", "4", "5", "6", "7", "11", "12"}


def validate(workspace: Path) -> ValidationResult:
    result = check_basic(workspace, "routes.txt", REQUIRED_COLUMNS)
    if result.status != "completed":
        return result

    records = read_csv_records(workspace / "routes.txt")
    agency_ids = _load_agency_ids(workspace)

    nameless: list[str] = []
    bad_type: list[str] = []
    bad_agency: list[str] = []

    for rec in records:
        route_id = (rec.get("route_id") or "").strip() or "(ID未設定)"
        short = (rec.get("route_short_name") or "").strip()
        long = (rec.get("route_long_name") or "").strip()
        # route_short_name / route_long_name のどちらか必須 (v4)
        if not short and not long:
            nameless.append(route_id)

        route_type = (rec.get("route_type") or "").strip()
        if route_type not in _VALID_ROUTE_TYPES:
            bad_type.append(f"{route_id}({route_type or '空'})")

        agency_id = (rec.get("agency_id") or "").strip()
        # agency.txt が存在する場合のみ参照整合をチェック
        if agency_ids and agency_id and agency_id not in agency_ids:
            bad_agency.append(f"{route_id}→{agency_id}")

    if nameless:
        result.status = "error"
        result.blockers.append(
            f"routes.txt: 路線名 (route_short_name/route_long_name) が"
            f"両方空の路線が {len(nameless)}件: {'、'.join(nameless[:5])}"
        )
    if bad_type:
        result.status = "error"
        result.blockers.append(
            f"routes.txt: route_type が不正な路線が {len(bad_type)}件: "
            f"{'、'.join(bad_type[:5])}"
        )
    if bad_agency:
        result.warnings.append(
            f"routes.txt: agency.txt に存在しない agency_id を参照: "
            f"{'、'.join(bad_agency[:5])}"
        )

    return result


def _load_agency_ids(workspace: Path) -> set[str]:
    """agency.txt から agency_id の集合を読む。無ければ空集合。"""
    path = workspace / "agency.txt"
    if not path.exists():
        return set()
    return {
        (rec.get("agency_id") or "").strip()
        for rec in read_csv_records(path)
        if (rec.get("agency_id") or "").strip()
    }
