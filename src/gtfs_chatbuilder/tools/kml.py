"""KML→座標テキスト変換ツール (@tool ラッパ)。

純粋な解析処理は processors.kml に Python 実装してある。ここはその呼び出しと、
workspace への「1経路1ファイル」書き出しを担う。

出力ファイル名は <kmlのbasename>__<placemark名>.txt。中身は
"経度,緯度,高度" の行が並んだテキストで、generate_shapes_from_coordinates に
そのまま渡せる。
"""

import re
from pathlib import Path

from langchain.tools import tool

from gtfs_chatbuilder.paths import WORKSPACE_DIR
from gtfs_chatbuilder.processors.encoding import read_text_auto
from gtfs_chatbuilder.processors.kml import process_kml_data

_SAFE_NAME_RE = re.compile(r"[^\w\-]+", re.UNICODE)


def _sanitize(name: str) -> str:
    """ファイル名に使える形に正規化する。"""
    cleaned = _SAFE_NAME_RE.sub("_", name).strip("_")
    return cleaned or "route"


@tool
def convert_kml_to_coordinates(kml_filename: str) -> str:
    """KMLファイルから経路ごとの座標テキストを抽出して個別ファイルに書き出す。

    KML 内の各 Placemark について以下の形式に対応:
    - LineString
    - Polygon (outerBoundaryIs/LinearRing)
    - gx:Track (GPSトラッキング)

    出力ファイルは workspace/ に "<kmlのbasename>__<placemark名>.txt" として
    1経路1ファイルで書き出される。中身は "経度,緯度,高度" の行が並んだ
    テキストで、これを generate_shapes_from_coordinates にそのまま渡せる。

    Args:
        kml_filename: KMLファイル名 (例: "route.kml")

    Returns:
        抽出した経路の一覧 (placemark名と出力ファイル名)
    """
    kml = WORKSPACE_DIR / kml_filename
    if not kml.exists():
        return f"エラー: KMLファイルが見つかりません: {kml}"

    try:
        kml_content = read_text_auto(kml)
    except UnicodeDecodeError as e:
        return f"エラー: KML のエンコード判定に失敗: {e}"

    try:
        items = process_kml_data(kml_content)
    except ValueError as e:
        return f"エラー: KML 解析に失敗しました: {e}"

    basename = Path(kml_filename).stem
    written: list[tuple[str, str]] = []
    used_names: set[str] = set()

    for item in items:
        name = item.get("name") or "route"
        coords = item.get("coordinates") or ""
        if not coords:
            continue

        safe = _sanitize(name)
        candidate = f"{basename}__{safe}.txt"
        i = 2
        while candidate in used_names:
            candidate = f"{basename}__{safe}_{i}.txt"
            i += 1
        used_names.add(candidate)

        out_path = WORKSPACE_DIR / candidate
        out_path.write_text(coords + "\n", encoding="utf-8")
        written.append((name, candidate))

    if not written:
        return "エラー: KMLから有効な経路が抽出できませんでした。"

    lines = [f"KMLから {len(written)} 経路を抽出しました:"]
    for name, filename in written:
        lines.append(f"  - {name} → {filename}")
    lines.append("")
    lines.append(
        "次の手順: generate_shapes_from_coordinates に shape_id と "
        "上記ファイル名を渡すと shapes.txt が生成できます。"
    )
    return "\n".join(lines)
