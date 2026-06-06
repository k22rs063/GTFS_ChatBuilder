"""stop_times.txt 生成 (里村ツール utils/stopTimesProcessor.js の Python 移植)。

入力:
- stops_content: stops.txt の本文。stop_name (token[2]) → stop_id_base (token[0] を
  "_" で split した先頭) のマップを構築するために使う。
- stop_times_data: 時刻表テキスト (CSV)。先頭行は "stop_name" で始まる必要がある。

出力: GTFS stop_times.txt 形式の CSV 文字列。ヘッダー:

    trip_id,arrival_time,departure_time,stop_id,stop_sequence,
    stop_headsign,pickup_type,drop_off_type,shape_dist_traveled,timepoint

サポートする入力フォーマット:
- 旧形式: stop_name, trip1, trip2, ... (各列が便で、セルが時刻)
- ewns 形式: ... ewns, stop_headsign, pickup_type, ... の列が末尾に付く
- 列グループ化形式: ヘッダーが "trip:time" / "trip:stop_headsign" のように
  ":" で区切られているか、2行目に property header (time/stop_headsign 等) がある形
- 便名列の直後にオプション列が連なる形式 (detectTripWithOptions)

JS 版にあった console.log は Python では出さない (純粋関数として保つ)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PROPERTY_ALIASES: dict[str, list[str]] = {
    "time": ["time", "時刻", "時間", "発車時刻", "到着時刻", "便時刻", "hour", "clock"],
    "stop_headsign": ["stop_headsign", "headsign", "行先", "行き先", "方面", "ゆき先"],
    "pickup_type": [
        "pickup_type", "pickup", "乗車可否", "乗車可", "乗車タイプ", "乗車",
        "pickup type",
    ],
    "drop_off_type": [
        "drop_off_type", "dropoff", "降車可否", "降車可", "降車タイプ", "降車",
        "drop off type",
    ],
    "shape_dist_traveled": [
        "shape_dist_traveled", "distance", "距離", "距離(m)", "走行距離",
    ],
    "timepoint": [
        "timepoint", "time_point", "基準", "基準時刻", "通過扱い", "時刻固定", "時点",
    ],
}


def _build_alias_lookup(aliases: dict[str, list[str]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            if not alias:
                continue
            lookup[alias.strip().lower()] = canonical
    return lookup


_PROPERTY_ALIAS_LOOKUP = _build_alias_lookup(PROPERTY_ALIASES)


@dataclass
class _TripGroup:
    name: str
    order: int
    time: int | None = None
    stop_headsign: int | None = None
    pickup_type: int | None = None
    drop_off_type: int | None = None
    shape_dist_traveled: int | None = None
    timepoint: int | None = None


_OUT_HEADER = (
    "trip_id,arrival_time,departure_time,stop_id,stop_sequence,"
    "stop_headsign,pickup_type,drop_off_type,shape_dist_traveled,timepoint\n"
)

_DIRECTION_CODES = {"l", "r", "lr", "rl", "e", "w", "n", "s"}
_OPTION_COLUMN_NAMES = (
    "stop_headsign",
    "pickup_type",
    "drop_off_type",
    "shape_dist_traveled",
    "timepoint",
)


def process_stop_times_data(stops_content: str, stop_times_data: str) -> str:
    """stops.txt と時刻表 CSV から stop_times.txt 用の CSV テキストを生成する。"""
    if not stops_content or not stop_times_data:
        raise ValueError("Stops.txtファイルと停留所時刻データが必要です")

    stops_info = _build_stops_info(stops_content)

    lines = [
        ln for ln in stop_times_data.split("\n") if ln.strip() != ""
    ]
    # stop_times_data は CRLF も来うるので、各行の \r を除去
    lines = [ln.rstrip("\r") for ln in lines]

    if not lines or not lines[0].startswith("stop_name"):
        raise ValueError(
            "有効な停留所時刻データが見つかりません。"
            "stop_nameで始まるヘッダーが必要です。"
        )

    parsed_lines = [
        [tok.strip() for tok in line.split(",")] for line in lines
    ]
    property_headers, data_start_row = _detect_property_header(parsed_lines)
    headings = parsed_lines[0]
    if not headings:
        raise ValueError("ヘッダー行を解析できませんでした")

    new_words = _OUT_HEADER

    ewns_index = next(
        (
            i
            for i, h in enumerate(headings)
            if h and h.strip().lower() == "ewns"
        ),
        -1,
    )
    stop_headsign_index = (
        headings.index("stop_headsign") if "stop_headsign" in headings else -1
    )

    has_multiple_option_columns = any(
        sum(1 for h in headings if h and h.strip().lower() == name) > 1
        for name in _OPTION_COLUMN_NAMES
    )
    has_trip_followed_by_options = _detect_trip_with_options(
        headings, ewns_index
    )
    is_column_grouped_format = (
        property_headers is not None
        or any(h and ":" in h for h in headings)
        or has_multiple_option_columns
        or has_trip_followed_by_options
    )
    is_new_format = (
        (ewns_index != -1 and stop_headsign_index != -1)
        or is_column_grouped_format
    )

    pickup_type_index = (
        headings.index("pickup_type")
        if is_new_format and "pickup_type" in headings
        else -1
    )
    drop_off_type_index = (
        headings.index("drop_off_type")
        if is_new_format and "drop_off_type" in headings
        else -1
    )
    shape_dist_traveled_index = (
        headings.index("shape_dist_traveled")
        if is_new_format and "shape_dist_traveled" in headings
        else -1
    )
    timepoint_index = (
        headings.index("timepoint")
        if is_new_format and "timepoint" in headings
        else -1
    )

    last_trip_column = (
        ewns_index
        if is_new_format and not is_column_grouped_format
        else len(headings)
    )

    if is_column_grouped_format:
        groups = _build_trip_groups(headings, ewns_index, property_headers)
        if not groups:
            raise ValueError("便ごとの列情報を特定できませんでした")
        new_words += _render_column_grouped(
            groups, parsed_lines, data_start_row, ewns_index, stops_info
        )
    else:
        new_words += _render_legacy_format(
            parsed_lines=parsed_lines,
            headings=headings,
            data_start_row=data_start_row,
            last_trip_column=last_trip_column,
            is_new_format=is_new_format,
            ewns_index=ewns_index,
            stop_headsign_index=stop_headsign_index,
            pickup_type_index=pickup_type_index,
            drop_off_type_index=drop_off_type_index,
            shape_dist_traveled_index=shape_dist_traveled_index,
            timepoint_index=timepoint_index,
            stops_info=stops_info,
        )

    # 末尾の連続改行を削除 (JS 版と同じ)
    return re.sub(r"[\n\r]+$", "", new_words)


def _build_stops_info(stops_content: str) -> dict[str, str]:
    """stops.txt から { stop_name: stop_id_base } の辞書を作る。

    JS 版と同じく、token[0] (stop_id) を "_" で分割した先頭を base とし、
    token[2] (stop_name) を key にする。同じ stop_name が複数あれば先勝ち。
    """
    stops_info: dict[str, str] = {}
    stops_lines = stops_content.split("\n")
    for i in range(1, len(stops_lines)):
        tokens = stops_lines[i].split(",")
        if len(tokens) >= 3 and tokens[2] not in stops_info:
            stops_info[tokens[2]] = tokens[0].split("_")[0]
    return stops_info


# ---------- 列グループ化形式 ----------


def _render_column_grouped(
    groups: list[_TripGroup],
    parsed_lines: list[list[str]],
    data_start_row: int,
    ewns_index: int,
    stops_info: dict[str, str],
) -> str:
    out: list[str] = []
    for group in groups:
        if group.time is None:
            continue
        stop_sequence = 0
        start_dist: float | None = None

        for row in range(data_start_row, len(parsed_lines)):
            tokens = parsed_lines[row] if row < len(parsed_lines) else []
            raw_time = _get_token_value(tokens, group.time)
            if not _is_valid_time_value(raw_time):
                continue
            time_value = _normalize_time_value(raw_time)

            if start_dist is None and group.shape_dist_traveled is not None:
                first_dist = _to_float(
                    _get_token_value(tokens, group.shape_dist_traveled)
                )
                if first_dist is not None:
                    start_dist = first_dist

            stop_name = tokens[0] if tokens else ""
            stop_id_base = stops_info.get(stop_name, stop_name or "")

            if ewns_index != -1 and _get_token_value(tokens, ewns_index):
                stop_id = stop_id_base + _get_token_value(tokens, ewns_index)
            elif len(tokens) > 1 and tokens[1] and ":" not in tokens[1]:
                stop_id = _strip_direction_suffix(stop_id_base) + tokens[1]
            else:
                stop_id = stop_id_base

            is_last_stop = not _lookahead_check(parsed_lines, group.time, row)
            sequence_value = stop_sequence

            # stop_headsign は GTFS 仕様上「行き先(終点)」を意味する。
            # 明示値が無ければ空欄。trip 全体の行き先は trips.trip_headsign 側で扱う。
            if is_last_stop:
                headsign = ""
            else:
                headsign = _get_token_value(tokens, group.stop_headsign)

            pickup_raw = _get_token_value(tokens, group.pickup_type)
            dropoff_raw = _get_token_value(tokens, group.drop_off_type)
            timepoint_raw = _get_token_value(tokens, group.timepoint)

            shape_distance = ""
            if group.shape_dist_traveled is not None:
                dist_value = _to_float(
                    _get_token_value(tokens, group.shape_dist_traveled)
                )
                if dist_value is not None:
                    if start_dist is None:
                        start_dist = dist_value
                    shape_distance = f"{(dist_value - start_dist):.0f}"

            pickup_out = "1" if is_last_stop else (pickup_raw or "0")
            dropoff_out = "1" if stop_sequence == 0 else (dropoff_raw or "0")

            out.append(
                f"{group.name},{time_value},{time_value},"
                f"{_normalize_stop_id_suffix(stop_id)},{sequence_value},"
                f"{headsign},{pickup_out},{dropoff_out},"
                f"{shape_distance},{timepoint_raw or ''}\n"
            )
            stop_sequence += 1
    return "".join(out)


# ---------- 旧 / ewns 形式 ----------


def _render_legacy_format(
    *,
    parsed_lines: list[list[str]],
    headings: list[str],
    data_start_row: int,
    last_trip_column: int,
    is_new_format: bool,
    ewns_index: int,
    stop_headsign_index: int,
    pickup_type_index: int,
    drop_off_type_index: int,
    shape_dist_traveled_index: int,
    timepoint_index: int,
    stops_info: dict[str, str],
) -> str:
    out: list[str] = []
    for col in range(1, last_trip_column):
        stop_sequence = 0
        start_dist = 0.0
        is_first_time_added = True

        for row in range(data_start_row, len(parsed_lines)):
            tokens = list(parsed_lines[row]) if row < len(parsed_lines) else []
            if (
                col >= len(tokens)
                or not tokens[col]
                or ":" not in tokens[col]
            ):
                continue
            time_value = _normalize_time_value(tokens[col])

            if is_new_format and is_first_time_added:
                if (
                    shape_dist_traveled_index != -1
                    and shape_dist_traveled_index < len(tokens)
                    and tokens[shape_dist_traveled_index]
                ):
                    d = _to_float(tokens[shape_dist_traveled_index])
                    if d is not None:
                        start_dist = d
                is_first_time_added = False

            stop_name = tokens[0] if tokens else ""
            stop_id_base = stops_info.get(stop_name, "")

            if (
                is_new_format
                and ewns_index != -1
                and ewns_index < len(tokens)
                and tokens[ewns_index]
            ):
                stop_id = stop_id_base + tokens[ewns_index]
            elif is_new_format:
                stop_id = stop_id_base
            elif (
                col > 0
                and col - 1 < len(tokens)
                and tokens[col - 1]
                and tokens[col - 1].strip().lower() in _DIRECTION_CODES
            ):
                stop_id = _strip_direction_suffix(stop_id_base) + tokens[col - 1]
            elif (
                len(tokens) > 1
                and tokens[1]
                and tokens[1].strip().lower() in _DIRECTION_CODES
            ):
                stop_id = _strip_direction_suffix(stop_id_base) + tokens[1]
            else:
                stop_id = stop_id_base

            is_last_stop = not _lookahead_check(parsed_lines, col, row)
            seq = stop_sequence

            line_parts: list[str] = []
            line_parts.append(headings[col])  # trip_id
            line_parts.append(time_value)  # arrival_time
            line_parts.append(time_value)  # departure_time
            line_parts.append(_normalize_stop_id_suffix(stop_id))  # stop_id
            line_parts.append(str(seq))  # stop_sequence

            # stop_headsign は GTFS 仕様上「行き先(終点)」を意味する。
            # 明示値 (col 番号付き ";" 区切りで指定された値) があれば採用、
            # 無ければ空欄。trip 全体の行き先は trips.trip_headsign 側で扱う。
            if is_last_stop:
                headsign_cell = ""
            else:
                headsign = ""
                if (
                    is_new_format
                    and stop_headsign_index != -1
                    and stop_headsign_index < len(tokens)
                    and tokens[stop_headsign_index]
                ):
                    parts = tokens[stop_headsign_index].split(";")
                    k = 0
                    while k < len(parts):
                        if k + 1 < len(parts):
                            try:
                                if int(parts[k]) == col:
                                    headsign = parts[k + 1]
                                    break
                            except ValueError:
                                pass
                        k += 2
                headsign_cell = headsign
            line_parts.append(headsign_cell)

            # pickup_type
            if is_last_stop:
                pickup_cell = "1"
            elif (
                is_new_format
                and pickup_type_index != -1
                and pickup_type_index < len(tokens)
                and tokens[pickup_type_index]
            ):
                pickup_cell = tokens[pickup_type_index]
            else:
                pickup_cell = "0"
            line_parts.append(pickup_cell)

            # drop_off_type
            if stop_sequence == 0:
                dropoff_cell = "1"
            elif (
                is_new_format
                and drop_off_type_index != -1
                and drop_off_type_index < len(tokens)
                and tokens[drop_off_type_index]
            ):
                dropoff_cell = tokens[drop_off_type_index]
            else:
                dropoff_cell = "0"
            line_parts.append(dropoff_cell)

            # shape_dist_traveled
            if (
                is_new_format
                and shape_dist_traveled_index != -1
                and shape_dist_traveled_index < len(tokens)
                and tokens[shape_dist_traveled_index]
            ):
                d = _to_float(tokens[shape_dist_traveled_index])
                if d is not None:
                    line_parts.append(f"{(d - start_dist):.0f}")
                else:
                    line_parts.append("")
            else:
                line_parts.append("")

            # timepoint
            if (
                is_new_format
                and timepoint_index != -1
                and timepoint_index < len(tokens)
                and tokens[timepoint_index]
            ):
                line_parts.append(tokens[timepoint_index])
            else:
                line_parts.append("")

            out.append(",".join(line_parts) + "\n")
            stop_sequence += 1
    return "".join(out)


# ---------- ヘルパ ----------


def _lookahead_check(
    lines: list[list[str]], column_index: int, line_index: int
) -> bool:
    """次行以降に同じ列に時刻 (":" を含むセル) があれば True。"""
    for j in range(line_index + 1, len(lines)):
        tokens = lines[j] if j < len(lines) else []
        if (
            len(tokens) > column_index
            and tokens[column_index]
            and ":" in tokens[column_index]
        ):
            return True
    return False


def _detect_trip_with_options(headings: list[str], ewns_index: int) -> bool:
    """便名列のあとにオプション列 (stop_headsign/pickup_type 等) が続く形式か。"""
    limit = ewns_index if ewns_index != -1 else len(headings)
    option_names = set(_OPTION_COLUMN_NAMES)

    found_trip_column = False
    for col in range(1, limit):
        header = headings[col] if col < len(headings) else ""
        if not header:
            continue
        normalized = header.strip().lower()
        property_name = _normalize_property_name(header)
        is_option_column = (
            normalized in option_names
            or (property_name is not None and property_name != "time")
        )
        if not is_option_column:
            found_trip_column = True
        elif found_trip_column:
            return True
    return False


def _build_trip_groups(
    headings: list[str],
    ewns_index: int,
    property_headers: list[str] | None,
) -> list[_TripGroup]:
    """列ヘッダーから便ごとのグループ (時刻列 + オプション列) を構築。"""
    limit = ewns_index if ewns_index != -1 else len(headings)
    groups: list[_TripGroup] = []
    current_group: _TripGroup | None = None
    group_counter = 1
    option_set = set(_OPTION_COLUMN_NAMES)

    for col in range(1, limit):
        header_raw = headings[col] if col < len(headings) else ""
        base_name, prop = _parse_header_cell(header_raw)

        if not prop and property_headers and col < len(property_headers):
            prop = _normalize_property_name(property_headers[col])

        if not prop:
            header_lower = (header_raw or "").strip().lower()
            if header_lower in option_set:
                prop = _normalize_property_name(header_raw)

        if not prop:
            prop = "time"

        if prop == "time":
            group_name = base_name or f"trip_{group_counter}"
            if not group_name.strip():
                group_name = f"trip_{group_counter}"
            current_group = _TripGroup(name=group_name, order=col, time=col)
            groups.append(current_group)
            group_counter += 1
            continue

        # オプション列
        if current_group is None:
            placeholder_name = base_name or f"trip_{group_counter}"
            group_counter += 1
            current_group = _TripGroup(name=placeholder_name, order=col)
            groups.append(current_group)

        if getattr(current_group, prop) is None:
            setattr(current_group, prop, col)

    finalized = [g for g in groups if g.time is not None]
    finalized.sort(key=lambda g: g.order)
    return finalized


def _get_token_value(tokens: list[str], index: int | None) -> str:
    if (
        not tokens
        or index is None
        or index < 0
        or index >= len(tokens)
    ):
        return ""
    return tokens[index].strip() if tokens[index] else ""


def _is_valid_time_value(value: str) -> bool:
    return bool(value and ":" in value)


_TIME_RE = re.compile(
    r"^([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?\s*(am|pm)?$", re.IGNORECASE
)


def _normalize_time_value(value: str) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    if not trimmed:
        return ""

    m = _TIME_RE.match(trimmed)
    if not m:
        return trimmed

    hour = int(m.group(1))
    minute = int(m.group(2))
    second = int(m.group(3)) if m.group(3) is not None else 0
    period = m.group(4).upper() if m.group(4) else None

    if period == "PM" and hour < 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0

    # 時間は先頭ゼロを取らない (= str(int))、分秒は 2 桁
    return f"{hour}:{minute:02d}:{second:02d}"


def _normalize_property_name(value: str | None) -> str | None:
    if not value:
        return None
    return _PROPERTY_ALIAS_LOOKUP.get(value.strip().lower())


def _detect_property_header(
    parsed_lines: list[list[str]],
) -> tuple[list[str] | None, int]:
    """2 行目が property header (time/headsign 等) なら (それ, 2) を返す。"""
    if len(parsed_lines) < 2:
        return None, 1

    candidate = parsed_lines[1] if len(parsed_lines) > 1 else []
    alias_count = sum(
        1 for cell in candidate if _normalize_property_name(cell)
    )
    has_time_values = any(_is_valid_time_value(cell) for cell in candidate)

    if alias_count > 0 and not has_time_values:
        return candidate, 2
    return None, 1


def _parse_header_cell(value: str) -> tuple[str, str | None]:
    """"trip1:time" → ("trip1", "time"), "stop_headsign" → ("", "stop_headsign")。"""
    if not value:
        return "", None
    raw = value.strip()
    if not raw:
        return "", None

    colon_index = raw.find(":")
    if colon_index != -1:
        base_name = raw[:colon_index].strip()
        prop = _normalize_property_name(raw[colon_index + 1:])
        return base_name, prop

    prop = _normalize_property_name(raw)
    if prop and prop != "time":
        return "", prop
    return raw, prop


# 方向サフィックス正規化 (JS 版と同じテーブル)
_SUFFIX_PATTERNS = ("lrlr", "rlrl", "ll", "rr", "lr", "rl", "l", "r")
_SUFFIX_NORMALIZED = {
    "lrlr": "lr", "rlrl": "rl", "ll": "l", "rr": "r",
    "lr": "lr", "rl": "rl", "l": "l", "r": "r",
}


def _normalize_stop_id_suffix(stop_id: str) -> str:
    """末尾が重複した方向サフィックス (ll/rr/lrlr 等) なら正規形に縮める。"""
    if not stop_id:
        return ""
    for pattern in _SUFFIX_PATTERNS:
        if stop_id.endswith(pattern):
            base = stop_id[: -len(pattern)]
            normalized = _SUFFIX_NORMALIZED[pattern]
            if pattern != normalized:
                return base + normalized
            break
    return stop_id


# ベースから方向サフィックスを剥がす (ewns は剥がさない)
_STRIP_PATTERNS = ("lr", "rl", "l", "r")


def _strip_direction_suffix(stop_id: str) -> str:
    if not stop_id:
        return ""
    for pattern in _STRIP_PATTERNS:
        if stop_id.endswith(pattern):
            return stop_id[: -len(pattern)]
    return stop_id


def _to_float(value: str) -> float | None:
    if not value:
        return None
    try:
        f = float(value)
    except (ValueError, TypeError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN/Inf を弾く
        return None
    return f
