"""バリデータ共通の型とユーティリティ。"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationResult:
    """1つの GTFSファイルに対するバリデーション結果。

    progress.py の StepProgress と対応する形で持たせる。
    """

    file_name: str
    status: str = "pending"  # pending|in_progress|completed|optional_pending|error
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fields_set: list[str] = field(default_factory=list)
    fields_missing: list[str] = field(default_factory=list)
    row_count: int = 0


def read_csv_header(path: Path) -> list[str] | None:
    """CSV の 1行目 (ヘッダー) を返す。読めなければ None。"""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            return next(reader, None)
    except (OSError, StopIteration):
        return None


def count_data_rows(path: Path) -> int:
    """データ行数 (ヘッダーを除く) を返す。読めなければ 0。"""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return max(sum(1 for _ in f) - 1, 0)
    except OSError:
        return 0


def read_csv_records(path: Path) -> list[dict[str, str]]:
    """CSV をヘッダー付き dict のリストとして読む。読めなければ空リスト。"""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def check_basic(
    workspace: Path,
    file_name: str,
    required_columns: list[str],
    is_optional: bool = False,
) -> ValidationResult:
    """基本的なファイル存在 + 必須列チェック。

    詳細なフィールド単位チェックは各 validator で追加する。
    """
    path = workspace / file_name
    result = ValidationResult(file_name=file_name)

    if not path.exists():
        result.status = "optional_pending" if is_optional else "pending"
        return result

    header = read_csv_header(path)
    if header is None:
        result.status = "error"
        result.blockers.append(f"{file_name}: 空 または 読み込めません")
        return result

    rows = count_data_rows(path)
    result.row_count = rows

    missing = [col for col in required_columns if col not in header]
    present = [col for col in required_columns if col in header]
    result.fields_set = present
    result.fields_missing = missing

    if missing:
        result.status = "error"
        result.blockers.append(
            f"{file_name}: 必須列が不足: {', '.join(missing)}"
        )
        return result

    if rows == 0:
        result.status = "in_progress"
        result.warnings.append(f"{file_name}: ヘッダーのみでデータ行がありません")
        return result

    result.status = "completed"
    return result
