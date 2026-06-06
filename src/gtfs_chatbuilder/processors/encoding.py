"""ファイル読み込み時のエンコーディング自動判定ヘルパ。

判定戦略は単純: utf-8-sig (BOM 有無問わず utf-8) → cp932 (Shift_JIS 系) の順で
strict に試行し、両方失敗したら明示的にエラーにする。

utf-8 / cp932 はいずれも strict デコーダなので、エンコードを取り違えると
ほぼ確実に UnicodeDecodeError が出る (= silent な文字化けは起きづらい)。
"""

from __future__ import annotations

from pathlib import Path

# 試行順: utf-8 系を優先 (近年の自治体配布物は utf-8 が増えている)。
_TRY_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp932")


def read_text_auto(path: Path) -> str:
    """ファイル本文を自動判定で読み込む。

    Raises:
        UnicodeDecodeError: 試行したすべてのエンコーディングで失敗したとき。
            メッセージに試行リストとファイルパスを含める。
    """
    last_error: UnicodeDecodeError | None = None
    for enc in _TRY_ENCODINGS:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError as e:
            last_error = e
            continue
    assert last_error is not None
    raise UnicodeDecodeError(
        last_error.encoding,
        last_error.object,
        last_error.start,
        last_error.end,
        (
            f"ファイルのエンコーディングを判定できませんでした "
            f"(試行: {', '.join(_TRY_ENCODINGS)})。ファイル: {path}"
        ),
    )
