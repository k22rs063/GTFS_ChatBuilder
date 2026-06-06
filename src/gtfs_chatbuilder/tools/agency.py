"""agency.txt 生成ツール (set_agency)。

GTFS-JP v4 必須ファイル。事業者の基本情報を 1 レコード書き込む。
現状は 1 workspace = 1 事業者 (design_state_management.md)。

LLM はユーザー発話から値を抽出して引数に詰めるだけ。値の生成・推論はしない
([[LLM is router only]])。
"""

from __future__ import annotations

from langchain.tools import tool

from gtfs_chatbuilder.gtfs_writer import write_gtfs_csv
from gtfs_chatbuilder.paths import WORKSPACE_DIR
from gtfs_chatbuilder.progress import load_progress, save_progress

# agency.txt のフィールド順 (v4 値の設定方法の順序)
_HEADER = [
    "agency_id",
    "agency_name",
    "agency_url",
    "agency_timezone",
    "agency_lang",
    "agency_phone",
    "agency_fare_url",
    "agency_email",
]


@tool
def set_agency(
    agency_name: str,
    agency_url: str,
    agency_id: str = "",
    agency_phone: str = "",
    agency_email: str = "",
    agency_fare_url: str = "",
    agency_timezone: str = "Asia/Tokyo",
    agency_lang: str = "ja",
) -> str:
    """事業者情報を agency.txt に書き込む (GTFS-JP v4 必須ファイル)。

    自治体が運営するコミュニティバスでは、agency_name に自治体名を設定する。
    値はユーザーが明示的に伝えたものだけを渡すこと。不明な項目は空のままにし、
    勝手に推測しないこと。

    Args:
        agency_name: 事業者名 (必須)。自治体名やバス会社名。例: "築上町"
        agency_url: 事業者のウェブサイトURL (必須)。
        agency_id: 事業者ID (任意)。法人番号13桁を推奨。空なら自動採番する。
        agency_phone: 問い合わせ電話番号 (任意・推奨)。例: "0930-56-0300"
        agency_email: 問い合わせメールアドレス (任意・推奨)。
        agency_fare_url: 運賃情報ページのURL (任意・推奨)。
        agency_timezone: タイムゾーン (既定: Asia/Tokyo)。国内なら変更不要。
        agency_lang: 言語コード (既定: ja)。国内なら変更不要。

    Returns:
        生成結果のサマリ。
    """
    agency_name = (agency_name or "").strip()
    agency_url = (agency_url or "").strip()

    missing = []
    if not agency_name:
        missing.append("agency_name (事業者名)")
    if not agency_url:
        missing.append("agency_url (事業者URL)")
    if missing:
        return (
            "エラー: 必須項目が不足しています: "
            + ", ".join(missing)
            + "。ユーザーに確認してください。"
        )

    agency_id = (agency_id or "").strip() or "agency_1"

    row = [
        agency_id,
        agency_name,
        agency_url,
        (agency_timezone or "Asia/Tokyo").strip(),
        (agency_lang or "ja").strip(),
        (agency_phone or "").strip(),
        (agency_fare_url or "").strip(),
        (agency_email or "").strip(),
    ]

    output = WORKSPACE_DIR / "agency.txt"
    write_gtfs_csv(output, _HEADER, [row])

    _update_progress(row)

    return (
        f"agency.txt を生成しました。\n"
        f"  事業者名: {agency_name}\n"
        f"  agency_id: {agency_id}\n"
        f"出力先: {output}"
    )


def _update_progress(row: list[str]) -> None:
    """メタファイル (.gtfs_progress.json) の agency ステップを更新する。

    ツールがメタファイルを更新する規約の最初の実装。
    実状態の確定判定は validator (get_project_status 経由) に委ねる。
    """
    progress = load_progress()
    step = progress.steps.get("agency")
    if step is None:
        return
    step.status = "completed"
    step.source_files = ["chat"]
    # 値が入っているフィールドのみ fields_set に記録
    step.fields_set = [name for name, value in zip(_HEADER, row) if value]
    step.fields_missing = []
    save_progress(progress)
