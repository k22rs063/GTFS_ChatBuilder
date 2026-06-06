"""stop_times.txt 生成ツール (@tool ラッパ)。

純粋な変換処理は processors 配下に Python 実装してある。ここは workspace
上のファイル入出力と LLM への結果報告のみを担当する。

パイプラインは
    timetable_io.read_timetable_sources()  ← CSV / xlsx 読み込み
        → timetable_normalizer.normalize_timetable()  ← テンプレ形式に正規化
            → stop_times.process_stop_times_data()  ← GTFS stop_times.txt 生成
の 3 段。確認層は中段 (normalize 後のテンプレ CSV) を利用者に見せる。
"""

from pathlib import Path

from langchain.tools import tool

from gtfs_chatbuilder.paths import WORKSPACE_DIR
from gtfs_chatbuilder.processors.stop_times import process_stop_times_data
from gtfs_chatbuilder.processors.timetable_io import read_timetable_sources
from gtfs_chatbuilder.processors.timetable_normalizer import normalize_timetable


def _read_stops(stops_path: Path) -> str:
    try:
        return stops_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return stops_path.read_text(encoding="cp932")


@tool
def generate_stop_times_from_csv(
    input_csv_filename: str,
    stops_filename: str = "stops.txt",
    output_filename: str = "stop_times.txt",
) -> str:
    """時刻表ファイルと stops.txt から GTFS の stop_times.txt を生成する。

    時刻表ファイルは CSV (.csv) または Excel (.xlsx / .xls) を受け付ける。
    Excel の場合、各シートを 1 系統の時刻表として個別に処理し、結果を連結する
    (2 シート目以降のヘッダー行は除外)。

    入力形式は柔軟で、内部の normalizer が次を吸収する:
    - ヘッダ行の位置 (路線名行や空行が前にあっても可)
    - 列名の別名 (停留所名/方角/行先 等 → stop_name/ewns/stop_headsign 等)
    - ewns 値の別名 (東/西/北/南、_w/_e 等 → e/w/n/s)

    出力には始発の drop_off_type=1、終着の pickup_type=1 が自動付与される。
    すべてのファイルは workspace/ フォルダ内を基準とする (パス区切りや
    上位ディレクトリ参照は使えない)。

    Args:
        input_csv_filename: 時刻表ファイル名 (.csv / .xlsx / .xls)
        stops_filename: stops.txt のファイル名 (省略時 "stops.txt")
        output_filename: 出力ファイル名 (省略時 "stop_times.txt")

    Returns:
        生成結果のサマリ (処理シート数・行数と出力先)
    """
    input_path = WORKSPACE_DIR / input_csv_filename
    stops = WORKSPACE_DIR / stops_filename
    output = WORKSPACE_DIR / output_filename

    if not input_path.exists():
        return f"エラー: 時刻表ファイルが見つかりません: {input_path}"
    if not stops.exists():
        return f"エラー: stops.txt が見つかりません: {stops}"

    stops_text = _read_stops(stops)

    try:
        sources = read_timetable_sources(input_path)
    except ValueError as e:
        return f"エラー: {e}"
    except Exception as e:  # noqa: BLE001 - openpyxl の例外を LLM に返す
        return f"エラー: 時刻表ファイルの読み込みに失敗しました: {e}"

    if not sources:
        return "エラー: 処理可能なシートが見つかりませんでした。"

    # 各シート / CSV を normalizer → processor の順で処理。
    # 2 つめ以降は最終出力のヘッダ行を除いて連結。
    parts: list[str] = []
    errors: list[str] = []
    for i, (name, text) in enumerate(sources):
        try:
            normalized = normalize_timetable(text)
            result_text = process_stop_times_data(stops_text, normalized)
        except ValueError as e:
            errors.append(f"[{name}] {e}")
            continue
        if i == 0 or not parts:
            parts.append(result_text)
        else:
            lines = result_text.strip().split("\n")
            if len(lines) > 1:
                parts.append("\n".join(lines[1:]))

    if not parts:
        msg = "; ".join(errors) if errors else "(空の出力)"
        return f"エラー: stop_times 生成に失敗しました: {msg}"

    final_text = "\n".join(parts)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(final_text, encoding="utf-8")

    data_rows = max(len(final_text.splitlines()) - 1, 0)
    suffix = input_path.suffix.lower()
    src_label = (
        f"{len(sources)}シート" if suffix in (".xlsx", ".xls") else "CSV"
    )
    summary = (
        f"stop_times.txt を生成しました ({src_label}, {data_rows}行)。\n"
        f"出力先: {output}"
    )
    if errors:
        summary += "\n警告: " + "; ".join(errors)
    return summary
