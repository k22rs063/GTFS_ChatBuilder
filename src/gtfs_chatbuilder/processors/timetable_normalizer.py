"""任意形式の時刻表テキストを、stop_times プロセッサが受けるテンプレ形式
(1 行目 stop_name で始まる CSV) に正規化する。

責務 (単一):
- 入力: 任意形式のテキスト (CSV / Excel コピペ; ヘッダ位置・列名さまざま)
- 出力: テンプレ形式 CSV テキスト (= process_stop_times_data が直接受ける形)

LLM は使わない (=不確実性が入らない)。入力構造を「時刻値パターン」で判定し、
ヘッダ別名と ewns 値別名を機械的に置換するだけ。元の値 (時刻・停留所名) は
転記のみで作らない。これにより「正規化結果を確認層が見せて利用者が承認」の
構図が成立する。
"""

from __future__ import annotations

import csv
import re
from io import StringIO

# 時刻セル判定 (HH:MM / HH:MM:SS)。AM/PM や空白付きは process_stop_times_data
# 側で正規化するのでここでは見ない。
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")

# ヘッダ別名: 入力ラベル → テンプレ正規名。
# 1 列目 (stop_name) は位置で決まるのでこの辞書には含めない。
_HEADER_ALIASES: dict[str, str] = {
    # 方向コード列
    "ewns": "ewns",
    "方角": "ewns",
    "方向": "ewns",
    # GTFS 拡張列 (process_stop_times_data 側の PROPERTY_ALIASES と整合)
    "stop_headsign": "stop_headsign",
    "行先": "stop_headsign",
    "行き先": "stop_headsign",
    "方面": "stop_headsign",
    "ゆき先": "stop_headsign",
    "pickup_type": "pickup_type",
    "乗車": "pickup_type",
    "乗車可否": "pickup_type",
    "乗車タイプ": "pickup_type",
    "drop_off_type": "drop_off_type",
    "降車": "drop_off_type",
    "降車可否": "drop_off_type",
    "降車タイプ": "drop_off_type",
    "shape_dist_traveled": "shape_dist_traveled",
    "距離": "shape_dist_traveled",
    "走行距離": "shape_dist_traveled",
    "timepoint": "timepoint",
    "基準": "timepoint",
    "基準時刻": "timepoint",
    "通過扱い": "timepoint",
    "時刻固定": "timepoint",
}

# ewns 列の値別名: 入力値 → 正規値 (e/w/n/s)。
_EWNS_VALUE_ALIASES: dict[str, str] = {
    "東": "e", "西": "w", "北": "n", "南": "s",
    "_e": "e", "_w": "w", "_n": "n", "_s": "s",
    "e": "e", "w": "w", "n": "n", "s": "s",
}


def normalize_timetable(raw_text: str) -> str:
    """任意形式の時刻表テキストを stop_times プロセッサ用テンプレ CSV に変換。

    変換規則:
    - 改行統一・BOM 除去・タブ → カンマ
    - 時刻値を含む最初の連続ブロックを「データ行」、その直前の非空行を
      「ヘッダ行」と判定 (路線名や空行をスキップ)
    - ヘッダ 1 列目は問答無用で `stop_name` に置換 (路線名や「往路」等が
      入っていても上書き)
    - 残りのヘッダは別名辞書 (`方角`→`ewns` 等) で正規化、未知のものは便名
      としてそのまま採用
    - ewns 列の値は別名辞書で e/w/n/s に解決
    - 元の時刻値・停留所名はそのまま転記する (LLM ではないので生成しない)

    Raises:
        ValueError: 時刻データやヘッダ行が見つからないとき。
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("時刻表テキストが空です")

    rows = _to_rows(raw_text)
    header_idx, data_indices = _detect_layout(rows)
    header = _normalize_header(rows[header_idx])
    data_rows = [rows[i] for i in data_indices]

    ewns_idx = _index_of(header, "ewns")
    if ewns_idx is not None:
        data_rows = [_normalize_ewns_value(r, ewns_idx) for r in data_rows]

    return _to_csv(header, data_rows)


def _to_rows(raw_text: str) -> list[list[str]]:
    """入力テキストを 2 次元リストにする (タブ区切りも受ける)。"""
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    text = "\n".join(line.replace("\t", ",") for line in text.split("\n"))
    return [
        [c.strip() for c in line.split(",")]
        for line in text.split("\n")
    ]


def _detect_layout(rows: list[list[str]]) -> tuple[int, list[int]]:
    """連続するデータ行ブロックを見つけ、(ヘッダ行 index, データ行 index 列) を返す。

    途中の空行はブロックを跨ぐ判定にしない (ヘッダ行直後に空行が挟まる稀なケースを許容)。
    時刻値以外の非空行に当たったらブロック終了 (= 別系統が来た等)。
    """
    data_indices: list[int] = []
    in_block = False
    for i, row in enumerate(rows):
        is_empty = not row or not any(c for c in row)
        if is_empty:
            continue
        if _is_time_row(row):
            data_indices.append(i)
            in_block = True
        elif in_block:
            break

    if not data_indices:
        raise ValueError(
            "時刻値 (HH:MM or HH:MM:SS) を含む行が見つかりませんでした"
        )

    first_data = data_indices[0]
    header_idx = None
    for i in range(first_data - 1, -1, -1):
        if rows[i] and any(c for c in rows[i]):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("ヘッダ行が見つかりませんでした")
    return header_idx, data_indices


def _is_time_row(row: list[str]) -> bool:
    """col 1 以降に時刻値を 1 つ以上含むか。"""
    return len(row) > 1 and any(c and _TIME_RE.match(c) for c in row[1:])


def _normalize_header(header: list[str]) -> list[str]:
    """ヘッダを正規化: 1 列目は stop_name 固定、残りは別名解決 or そのまま。"""
    result: list[str] = ["stop_name"]
    for cell in header[1:]:
        key = cell.strip()
        if not key:
            result.append("")
            continue
        normalized = (
            _HEADER_ALIASES.get(key)
            or _HEADER_ALIASES.get(key.lower())
        )
        result.append(normalized or cell)
    return result


def _index_of(header: list[str], target: str) -> int | None:
    for i, h in enumerate(header):
        if h == target:
            return i
    return None


def _normalize_ewns_value(row: list[str], ewns_idx: int) -> list[str]:
    """指定列の値が別名辞書にあれば e/w/n/s に解決する。"""
    if ewns_idx >= len(row):
        return row
    cell = row[ewns_idx].strip()
    if cell in _EWNS_VALUE_ALIASES:
        new = list(row)
        new[ewns_idx] = _EWNS_VALUE_ALIASES[cell]
        return new
    return row


def _to_csv(header: list[str], data_rows: list[list[str]]) -> str:
    buf = StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in data_rows:
        w.writerow(r)
    return buf.getvalue().rstrip("\n")
