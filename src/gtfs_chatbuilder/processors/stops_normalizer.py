"""自治体独自フォーマットの停留所情報 CSV を GTFS stops.txt に正規化する。

責務 (単一):
- 入力: 任意の停留所情報 CSV (cp932 / utf-8、ヘッダ別名さまざま)
- 出力: stop_id, stop_name, stop_lat, stop_lon の正規化 CSV テキスト

LLM は使わない。ヘッダ別名と緯度経度フォーマット (DMS / 十進数 / 結合列) を
機械的に判別して変換する。

対応する入力バリエーション:
- ヘッダ別名: 停留所名/バス停名/停留所/name、緯度/経度の個別列、緯度経度の結合列
- 緯度経度: 十進数 (33.6158) と DMS (33°36'56.9"N 131°03'52.5"E) の両方
- stop_id: 明示列 > No. 列 > 自動連番 (S1, S2, ...)
"""

from __future__ import annotations

import csv
import re
from io import StringIO

# ヘッダ別名: 入力ラベル → 内部正規化フィールド名
_HEADER_ALIASES: dict[str, str] = {
    # 停留所名
    "stop_name": "stop_name",
    "停留所名": "stop_name",
    "バス停名": "stop_name",
    "バス停": "stop_name",
    "停留所": "stop_name",
    "name": "stop_name",
    # stop_id (明示)
    "stop_id": "stop_id",
    "id": "stop_id",
    # No. (自動連番のヒント)
    "no.": "stop_id_num",
    "no": "stop_id_num",
    "番号": "stop_id_num",
    "#": "stop_id_num",
    # 緯度 / 経度 (個別列)
    "stop_lat": "stop_lat",
    "緯度": "stop_lat",
    "lat": "stop_lat",
    "latitude": "stop_lat",
    "stop_lon": "stop_lon",
    "経度": "stop_lon",
    "lon": "stop_lon",
    "lng": "stop_lon",
    "longitude": "stop_lon",
    # 緯度経度 結合列 (DMS が多い)
    "緯度経度": "latlon_combined",
    "経緯度": "latlon_combined",
    "lat_lon": "latlon_combined",
    "latlon": "latlon_combined",
    "coordinates": "latlon_combined",
}

# DMS パターン: 33°36'56.9"N 131°03'52.5"E (緯度 + 経度の結合)
_DMS_LATLON_RE = re.compile(
    r"(\d+)\s*[°度]\s*(\d+)\s*['′分]\s*(\d+(?:\.\d+)?)\s*[\"″秒]?\s*([NSns])"
    r"\s*"
    r"(\d+)\s*[°度]\s*(\d+)\s*['′分]\s*(\d+(?:\.\d+)?)\s*[\"″秒]?\s*([EWew])"
)

# 個別 DMS (1 値のみ)
_DMS_SINGLE_RE = re.compile(
    r"(\d+)\s*[°度]\s*(\d+)\s*['′分]\s*(\d+(?:\.\d+)?)\s*[\"″秒]?\s*([NSEWnsew])"
)


def normalize_stops(raw_text: str) -> str:
    """自治体独自 CSV を GTFS stops.txt 形式の正規化テキストに変換する。

    出力ヘッダ: stop_id, stop_name, stop_lat, stop_lon
    DMS は十進数 (小数点 6 桁) に変換。

    Raises:
        ValueError: 入力空 / 停留所名列が見つからない / 有効な行なし。
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("停留所 CSV が空です")

    rows = _to_rows(raw_text)
    if not rows:
        raise ValueError("CSV を解析できませんでした")

    header = rows[0]
    field_map = _map_header(header)

    if "stop_name" not in field_map:
        raise ValueError(
            "停留所名の列が見つかりません。"
            "「停留所名」「バス停名」「stop_name」等のヘッダを含めてください。"
        )

    data_rows = [r for r in rows[1:] if any(c.strip() for c in r)]
    if not data_rows:
        raise ValueError("有効なデータ行がありません")

    out_rows: list[list[str]] = []
    for i, row in enumerate(data_rows, start=1):
        stop_name = _safe_cell(row, field_map.get("stop_name"))
        if not stop_name:
            continue

        stop_id = _safe_cell(row, field_map.get("stop_id"))
        if not stop_id:
            no_val = _safe_cell(row, field_map.get("stop_id_num"))
            stop_id = f"S{no_val}" if no_val else f"S{i}"

        lat, lon = _extract_latlon(row, field_map)
        # GTFS 標準列順: stop_id, stop_code, stop_name, stop_lat, stop_lon
        # 後段 (stop_times プロセッサ) が tokens[2] を stop_name として参照するため、
        # 列順は厳密に守る必要がある。stop_code は任意項目なので空で OK。
        out_rows.append([stop_id, "", stop_name, lat, lon])

    if not out_rows:
        raise ValueError("有効な停留所がありませんでした")

    buf = StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["stop_id", "stop_code", "stop_name", "stop_lat", "stop_lon"])
    for r in out_rows:
        w.writerow(r)
    return buf.getvalue().rstrip("\n")


def _to_rows(raw: str) -> list[list[str]]:
    """CSV テキストを 2 次元リストに。タブ → カンマ、BOM 除去、quote 対応。"""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    text = "\n".join(line.replace("\t", ",") for line in text.split("\n"))
    return [[c.strip() for c in r] for r in csv.reader(StringIO(text))]


def _map_header(header: list[str]) -> dict[str, int]:
    """ヘッダから {正規化フィールド名: col_index} を作る。"""
    mapping: dict[str, int] = {}
    for i, cell in enumerate(header):
        key = cell.strip()
        normalized = (
            _HEADER_ALIASES.get(key.lower())
            or _HEADER_ALIASES.get(key)
        )
        if normalized and normalized not in mapping:
            mapping[normalized] = i
    return mapping


def _safe_cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


def _extract_latlon(
    row: list[str], field_map: dict[str, int]
) -> tuple[str, str]:
    """データ行から (lat, lon) を取り出す。複数フォーマットに対応。"""
    # 1. 個別の緯度 / 経度列
    if "stop_lat" in field_map or "stop_lon" in field_map:
        lat = _parse_coord(_safe_cell(row, field_map.get("stop_lat")))
        lon = _parse_coord(_safe_cell(row, field_map.get("stop_lon")))
        return lat, lon

    # 2. 緯度経度を 1 列にまとめた結合列
    if "latlon_combined" in field_map:
        combined = _safe_cell(row, field_map.get("latlon_combined"))
        m = _DMS_LATLON_RE.search(combined)
        if m:
            lat = _dms_to_decimal(
                int(m.group(1)),
                int(m.group(2)),
                float(m.group(3)),
                m.group(4),
            )
            lon = _dms_to_decimal(
                int(m.group(5)),
                int(m.group(6)),
                float(m.group(7)),
                m.group(8),
            )
            return f"{lat:.6f}", f"{lon:.6f}"
        # 結合列が十進数 "33.5, 131.0" の形式
        parts = re.split(r"[,\s/]+", combined)
        parts = [p for p in parts if p]
        if len(parts) >= 2:
            lat = _parse_coord(parts[0])
            lon = _parse_coord(parts[1])
            return lat, lon

    return "", ""


def _parse_coord(text: str) -> str:
    """単独の緯度 or 経度を十進数文字列に変換 (十進数ならそのまま、DMS なら変換)。"""
    if not text:
        return ""
    try:
        return f"{float(text):.6f}"
    except ValueError:
        pass
    m = _DMS_SINGLE_RE.search(text)
    if m:
        v = _dms_to_decimal(
            int(m.group(1)),
            int(m.group(2)),
            float(m.group(3)),
            m.group(4),
        )
        return f"{v:.6f}"
    return ""


def _dms_to_decimal(deg: int, min_: int, sec: float, direction: str) -> float:
    """度分秒 + 方位 (N/S/E/W) を十進数に。S と W は負にする。"""
    val = deg + min_ / 60.0 + sec / 3600.0
    if direction.upper() in ("S", "W"):
        val = -val
    return val
