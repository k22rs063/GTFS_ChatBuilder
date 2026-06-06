"""KML解析 (里村ツール utils/kmlProcessor.js の Python 移植)。

KML 内の各 Placemark について座標テキストを抽出する。対応形式:
- LineString
- Polygon (outerBoundaryIs/LinearRing)
- gx:Track (GPSトラッキング)

返却: [{"name": str, "coordinates": str}, ...]
coordinates は "経度,緯度,高度" の行を改行で連結した文字列。
LineString/Polygon 形式は KML 元のテキストをそのまま返し、gx:Track 形式は
内部で同じ形に変換してから返す (後段の shapes 生成側で同一処理にするため)。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# KML の名前空間。ElementTree は名前空間 URI を {uri}localname の形に
# 展開するので、ローカル名だけ取り出すために剥がす。
_NS_RE = re.compile(r"^\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    """{namespace}localname → localname。プレフィックス付きの場合は ':' 後を返す。"""
    no_ns = _NS_RE.sub("", tag)
    if ":" in no_ns:
        return no_ns.split(":", 1)[1]
    return no_ns


def _localname(elem: ET.Element) -> str:
    return _strip_ns(elem.tag)


def _find_children(parent: ET.Element, name: str) -> list[ET.Element]:
    """名前空間を無視して直下の子要素を name で絞り込む。"""
    return [c for c in parent if _localname(c) == name]


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    for c in parent:
        if _localname(c) == name:
            return c
    return None


def _text_of(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text


def process_kml_data(kml_content: str) -> list[dict[str, str]]:
    """KML 文字列から各 Placemark の (name, coordinates) を抽出する。

    Args:
        kml_content: KML ファイル本文 (UTF-8 文字列)。

    Returns:
        [{"name": ..., "coordinates": ...}, ...]

    Raises:
        ValueError: KML が空 / 構造不正 / 有効な座標なし のとき。
    """
    if not kml_content:
        raise ValueError("KMLファイルの内容が空です")

    try:
        root = ET.fromstring(kml_content)
    except ET.ParseError as e:
        raise ValueError(
            f"KMLデータの処理中にエラーが発生しました: {e}"
        ) from e

    # ルートが <kml> か、その中に Document があるか確認
    if _localname(root) != "kml":
        raise ValueError("KMLファイルの構造が正しくありません")

    documents = _find_children(root, "Document")
    if not documents:
        raise ValueError("KMLファイルの構造が正しくありません")

    items: list[dict[str, str]] = []

    for doc in documents:
        # ドキュメント名 (gx:Track 形式で Placemark に名前がないときに使う)
        doc_name = _text_of(_find_child(doc, "name")).strip()

        placemarks = _extract_placemarks(doc)
        for placemark in placemarks:
            name = _text_of(_find_child(placemark, "name")).strip()
            coordinates = ""

            # 1. LineString 形式
            line_string = _find_child(placemark, "LineString")
            if line_string is not None:
                coord_elem = _find_child(line_string, "coordinates")
                coordinates = _text_of(coord_elem)

            # 2. Polygon 形式
            if not coordinates:
                polygon = _find_child(placemark, "Polygon")
                if polygon is not None:
                    outer = _find_child(polygon, "outerBoundaryIs")
                    if outer is not None:
                        ring = _find_child(outer, "LinearRing")
                        if ring is not None:
                            coord_elem = _find_child(ring, "coordinates")
                            coordinates = _text_of(coord_elem)

            # 3. gx:Track 形式
            if not coordinates:
                track = _extract_gx_track_from_placemark(placemark)
                if track is not None:
                    coordinates = _extract_gx_track_coordinates(track)
                    # 名前が無ければドキュメント名を流用
                    if not name and doc_name:
                        name = doc_name

            if coordinates:
                if not name:
                    name = f"Route_{len(items) + 1}"
                items.append({"name": name, "coordinates": coordinates})

    if not items:
        raise ValueError("KMLファイルから有効な座標データが見つかりませんでした")

    return items


def _extract_placemarks(node: ET.Element) -> list[ET.Element]:
    """Placemark を再帰的に集める (Folder のネストに対応)。"""
    placemarks: list[ET.Element] = []
    placemarks.extend(_find_children(node, "Placemark"))
    for folder in _find_children(node, "Folder"):
        placemarks.extend(_extract_placemarks(folder))
    return placemarks


def _extract_gx_track_from_placemark(
    placemark: ET.Element,
) -> ET.Element | None:
    """Placemark から gx:Track を取り出す (gx:MultiTrack 内も探す)。"""
    track = _find_child(placemark, "Track")
    if track is not None:
        return track
    multi = _find_child(placemark, "MultiTrack")
    if multi is not None:
        return _find_child(multi, "Track")
    return None


def _extract_gx_track_coordinates(track: ET.Element) -> str:
    """gx:Track の <gx:coord>経度 緯度 高度</gx:coord> 群を LineString 形式に変換。"""
    coords: list[str] = []
    for coord_elem in _find_children(track, "coord"):
        coord_str = _text_of(coord_elem).strip()
        if not coord_str:
            continue
        parts = coord_str.split()
        if len(parts) < 2:
            continue
        lon = parts[0]
        lat = parts[1]
        alt = parts[2] if len(parts) >= 3 else "0"
        coords.append(f"{lon},{lat},{alt}")
    return "\n".join(coords)
