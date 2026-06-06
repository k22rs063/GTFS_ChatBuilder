"""shapes.txt 生成ツール (@tool ラッパ)。

純粋な変換処理は processors.shapes に Python 実装してある。ここは
workspace 上のファイル入出力と LLM への結果報告のみを担当する。
"""

from langchain.tools import tool

from gtfs_chatbuilder.paths import WORKSPACE_DIR
from gtfs_chatbuilder.processors.encoding import read_text_auto
from gtfs_chatbuilder.processors.shapes import process_shapes_data


@tool
def generate_shapes_from_coordinates(
    shape_id: str,
    coordinates_filename: str,
    output_filename: str = "shapes.txt",
) -> str:
    """座標テキストファイルと shape_id から GTFS の shapes.txt を生成する。

    座標テキストの想定フォーマット (1行1点):
    - "経度,緯度,任意の値" (例: "130.123456,33.654321,0")
    - 経度を9桁、緯度を8桁にゼロ埋めして整形される
    - shape_pt_sequence は行順 (1から) で自動付与される

    出力 CSV のヘッダー: shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence

    すべてのファイルは workspace/ フォルダ内を基準とする (パス区切りや
    上位ディレクトリ参照は使えない)。

    Args:
        shape_id: shapes.txt に書き込む shape_id (例: "shape_1")
        coordinates_filename: 座標テキストファイル名 (例: "route1.txt")
        output_filename: 出力ファイル名 (省略時 "shapes.txt")

    Returns:
        生成結果のサマリ (行数と出力先)
    """
    coords = WORKSPACE_DIR / coordinates_filename
    output = WORKSPACE_DIR / output_filename

    if not coords.exists():
        return f"エラー: 座標ファイルが見つかりません: {coords}"

    try:
        coord_text = read_text_auto(coords)
    except UnicodeDecodeError as e:
        return f"エラー: 座標ファイルのエンコード判定に失敗: {e}"

    try:
        csv_text = process_shapes_data(shape_id, coord_text)
    except ValueError as e:
        return f"エラー: shapes 生成に失敗しました: {e}"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(csv_text, encoding="utf-8")

    data_rows = max(len(csv_text.splitlines()) - 1, 0)
    return (
        f"shapes.txt を生成しました ({data_rows}行, shape_id={shape_id})。\n"
        f"出力先: {output}"
    )
