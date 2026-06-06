"""feed_info.txt 生成ツール (set_feed_info)。

GTFS-JP v4 必須ファイル。データセットの提供者・有効期間・バージョンを
1 レコード書き込む。

LLM はユーザー発話から値を抽出して引数に詰めるだけ。値の生成・推論はしない
([[LLM is router only]])。「2026年4月1日」→「20260401」の書式変換は許容。
"""

from __future__ import annotations

from datetime import datetime

from langchain.tools import tool

from gtfs_chatbuilder.gtfs_writer import write_gtfs_csv
from gtfs_chatbuilder.paths import WORKSPACE_DIR
from gtfs_chatbuilder.progress import load_progress, save_progress

# feed_info.txt のフィールド順 (v4 値の設定方法の順序)。
# default_lang は v4 で「不要」区分のため出力しない。
_HEADER = [
    "feed_publisher_name",
    "feed_publisher_url",
    "feed_lang",
    "feed_start_date",
    "feed_end_date",
    "feed_version",
    "feed_contact_email",
    "feed_contact_url",
]


@tool
def set_feed_info(
    feed_publisher_name: str,
    feed_publisher_url: str,
    feed_start_date: str,
    feed_end_date: str,
    feed_version: str = "",
    feed_contact_email: str = "",
    feed_contact_url: str = "",
    feed_lang: str = "ja",
) -> str:
    """データセット情報を feed_info.txt に書き込む (GTFS-JP v4 必須ファイル)。

    日付は YYYYMMDD 形式 (例: 2026年4月1日 → "20260401")。
    ユーザーが「2026年4月1日」のように伝えた場合はこの形式に変換して渡してよい。

    Args:
        feed_publisher_name: データを提供する組織の名称 (必須)。
        feed_publisher_url: 提供組織のウェブサイトURL (必須)。
        feed_start_date: データセット有効期間の開始日 (必須, YYYYMMDD)。
        feed_end_date: データセット有効期間の終了日 (必須, YYYYMMDD)。
        feed_version: データセットのバージョン (任意)。空なら開始日ベースで自動生成。
        feed_contact_email: データに関する技術的問い合わせ先メール (任意・推奨)。
        feed_contact_url: データに関する技術的問い合わせ先URL (任意・推奨)。
        feed_lang: データセットの言語 (既定: ja)。国内なら変更不要。

    Returns:
        生成結果のサマリ。
    """
    feed_publisher_name = (feed_publisher_name or "").strip()
    feed_publisher_url = (feed_publisher_url or "").strip()
    feed_start_date = (feed_start_date or "").strip()
    feed_end_date = (feed_end_date or "").strip()

    missing = []
    if not feed_publisher_name:
        missing.append("feed_publisher_name (提供組織名)")
    if not feed_publisher_url:
        missing.append("feed_publisher_url (提供組織URL)")
    if not feed_start_date:
        missing.append("feed_start_date (有効期間開始日)")
    if not feed_end_date:
        missing.append("feed_end_date (有効期間終了日)")
    if missing:
        return (
            "エラー: 必須項目が不足しています: "
            + ", ".join(missing)
            + "。ユーザーに確認してください。"
        )

    start_err = _validate_date(feed_start_date, "feed_start_date")
    if start_err:
        return start_err
    end_err = _validate_date(feed_end_date, "feed_end_date")
    if end_err:
        return end_err

    if feed_start_date > feed_end_date:
        return (
            f"エラー: 有効期間が逆転しています "
            f"(開始 {feed_start_date} > 終了 {feed_end_date})。"
        )

    feed_version = (feed_version or "").strip() or feed_start_date

    row = [
        feed_publisher_name,
        feed_publisher_url,
        (feed_lang or "ja").strip(),
        feed_start_date,
        feed_end_date,
        feed_version,
        (feed_contact_email or "").strip(),
        (feed_contact_url or "").strip(),
    ]

    output = WORKSPACE_DIR / "feed_info.txt"
    write_gtfs_csv(output, _HEADER, [row])

    _update_progress(row)

    return (
        f"feed_info.txt を生成しました。\n"
        f"  提供組織: {feed_publisher_name}\n"
        f"  有効期間: {feed_start_date} 〜 {feed_end_date}\n"
        f"  バージョン: {feed_version}\n"
        f"出力先: {output}"
    )


def _validate_date(value: str, field_name: str) -> str | None:
    """YYYYMMDD 形式かチェック。問題なければ None、あればエラー文字列を返す。"""
    if len(value) != 8 or not value.isdigit():
        return (
            f"エラー: {field_name} は YYYYMMDD 形式の8桁数字で指定してください "
            f"(受け取った値: {value!r})。"
        )
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return f"エラー: {field_name} が存在しない日付です (受け取った値: {value!r})。"
    return None


def _update_progress(row: list[str]) -> None:
    """メタファイル (.gtfs_progress.json) の feed_info ステップを更新する。"""
    progress = load_progress()
    step = progress.steps.get("feed_info")
    if step is None:
        return
    step.status = "completed"
    step.source_files = ["chat"]
    step.fields_set = [name for name, value in zip(_HEADER, row) if value]
    step.fields_missing = []
    save_progress(progress)
