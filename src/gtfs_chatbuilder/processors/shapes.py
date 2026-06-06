"""shapes.txt 生成 (里村ツール utils/shapesProcessor.js の Python 移植)。

入力: shape_id と座標テキスト ("経度,緯度,任意" を改行で並べたもの)。
出力: GTFS shapes.txt 形式の CSV テキスト

    shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence

オリジナルの JS と同じ挙動を保つため、次の癖をそのまま再現している:
- 経度を9桁、緯度を8桁にゼロ埋め (左詰めの文字列としてゼロを末尾に足す)
- 並び順は経度,緯度 → 出力時に lat,lon に入れ替え
- shape_pt_sequence は 1 始まりだが、空行を除外する前の行番号 (i+1) を使う
  ため、空行が無いケース (通常の KML→txt 出力) では結果として連番になる
- 1行目に "shape_id" が含まれていれば既存ヘッダーとみなしてヘッダーは追加しない
- 末尾改行は削除する

なお JS 版は正規表現にマッチしなかった行をそのまま追記する (壊れた行を
温存する) 挙動だが、後段 (GTFS バリデータ) を通せばそこで気付けるため
同じ挙動にしている。
"""

from __future__ import annotations

import re

_LINE_RE = re.compile(r"^([^,]+),([^,]+),[^,]*$")


def process_shapes_data(shape_id: str, coordinate_data: str) -> str:
    """shape_id と座標テキストから shapes.txt 用の CSV テキストを返す。

    Raises:
        ValueError: 引数空 / 有効座標なし のとき (元 JS と同じメッセージ)。
    """
    if not shape_id or not coordinate_data:
        raise ValueError("Shape IDと座標データが必要です")

    lines = [ln for ln in coordinate_data.split("\n") if ln.strip() != ""]

    if not lines:
        raise ValueError("有効な座標データが見つかりません")

    out_parts: list[str] = []

    header = "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence"
    if "shape_id" not in lines[0]:
        out_parts.append(header + "\n")

    for i, line in enumerate(lines):
        m = _LINE_RE.match(line)
        if not m:
            # マッチしない行はそのまま温存 (JS 版と同挙動)
            out_parts.append(line)
            continue

        lon = m.group(1).strip()
        lat = m.group(2)

        # 経度を 9 桁、緯度を 8 桁にゼロ埋め (末尾追加: 元 JS 仕様)
        if len(lon) < 9:
            lon = lon + "0" * (9 - len(lon))
        if len(lat) < 8:
            lat = lat + "0" * (8 - len(lat))

        out_parts.append(f"{shape_id},{lat},{lon},{i + 1}\n")

    new_words = "".join(out_parts)
    # 末尾の連続改行 (\n / \r) を削除
    return re.sub(r"[\n\r]+$", "", new_words)
