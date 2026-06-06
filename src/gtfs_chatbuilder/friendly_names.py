"""ツール名と引数名のユーザー向け日本語表記。

内部ツール名・引数名はそのままに、UI 上の表示だけ平易な日本語に置き換える。
ここに集約しておくことで、UI コードを触らずに表現を直せる。
"""

TOOL_LABELS: dict[str, str] = {
    "set_agency": "事業者情報の登録",
    "set_feed_info": "データセット情報の登録",
    "import_stops_from_excel": "停留所マスタの取り込み（Excel）",
    "generate_stops_from_csv": "停留所情報の取り込み（CSV）",
    "fill_stop_coordinates_from_kml": "停留所の座標を KML から補完",
    "import_routes_from_excel": "路線マスタの取り込み（Excel）",
    "generate_stop_times_from_csv": "時刻表データの作成",
    "generate_shapes_from_coordinates": "路線形状（経路）の作成",
    "convert_kml_to_coordinates": "KML から経路の座標を抽出",
    "get_project_status": "進捗の確認",
}

ARG_LABELS: dict[str, str] = {
    # agency
    "agency_id": "事業者 ID（任意）",
    "agency_name": "事業者名",
    "agency_url": "URL",
    "agency_phone": "電話番号",
    "agency_email": "メールアドレス",
    "agency_fare_url": "運賃情報 URL",
    "agency_timezone": "タイムゾーン",
    "agency_lang": "言語",
    # feed_info
    "feed_publisher_name": "提供組織名",
    "feed_publisher_url": "提供組織 URL",
    "feed_start_date": "有効期間 開始日",
    "feed_end_date": "有効期間 終了日",
    "feed_version": "バージョン",
    "feed_contact_email": "連絡先メール",
    "feed_contact_url": "連絡先 URL",
    "feed_lang": "言語",
    # stops / routes Excel
    "excel_filename": "Excel ファイル",
    # KML
    "kml_filename": "KML ファイル",
    # stop_times
    "input_csv_filename": "時刻表ファイル",
    "stops_filename": "停留所マスタ",
    "output_filename": "出力ファイル",
    # shapes
    "shape_id": "経路 ID",
    "coordinates_filename": "座標ファイル",
}


def tool_label(name: str) -> str:
    """内部ツール名 → 日本語ラベル。未定義ならそのまま返す。"""
    return TOOL_LABELS.get(name, name)


def arg_label(key: str) -> str:
    """引数キー → 日本語ラベル。未定義ならそのまま返す。"""
    return ARG_LABELS.get(key, key)
