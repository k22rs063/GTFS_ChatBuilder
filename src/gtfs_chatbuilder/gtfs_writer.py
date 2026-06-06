"""GTFS-JP v4 規約に従って CSV (.txt) ファイルを書く共通ヘルパー。

v4 仕様 (3.3 ファイル及びフィールドで利用可能な文字等):
- 文字コードは UTF-8、BOM を付けない
- 各行の末尾は CRLF または LF (本実装は LF を採用)
- 引用符またはコンマを含むフィールド値は引用符で囲む
- フィールド名・値の前後にスペースを入れない
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence


def write_gtfs_csv(
    path: Path,
    header: Sequence[str],
    rows: Sequence[Sequence[object]],
) -> int:
    """GTFS-JP v4 規約で CSV を書き込む。

    Args:
        path: 出力先 (.txt)
        header: フィールド名の並び
        rows: データ行 (各行は header と同じ長さの値の並び)

    Returns:
        書き込んだデータ行数 (ヘッダーを除く)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # encoding="utf-8" は BOM なし。newline="" は csv モジュールの作法。
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow([_clean(col) for col in header])
        for row in rows:
            writer.writerow([_clean(value) for value in row])
    return len(rows)


def _clean(value: object) -> str:
    """値を文字列化し、前後スペースを除去する (v4 規約: 値の前後にスペース禁止)。"""
    if value is None:
        return ""
    return str(value).strip()
