"""Streamlit エントリ (利用者確認層対応)。

書き込み系ツール呼び出し前に承認パネルを挟む。三層アーキテクチャの
ユーザー確認層を Streamlit 上で具現化したもの。
"""

import io
import uuid
import zipfile
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from gtfs_chatbuilder.agents import create_gtfs_agent
from gtfs_chatbuilder.controllers import (
    AgentResponse,
    PendingAction,
    invoke_agent,
    resume_agent,
)
from gtfs_chatbuilder.friendly_names import arg_label, tool_label, tool_summary
from gtfs_chatbuilder.paths import WORKSPACE_DIR
from gtfs_chatbuilder.processors.encoding import read_text_auto
from gtfs_chatbuilder.processors.timetable_io import read_timetable_sources
from gtfs_chatbuilder.processors.timetable_normalizer import normalize_timetable

load_dotenv()

st.set_page_config(
    page_title="GTFS-JP ChatBuilder",
    layout="wide",
)

# GTFS 標準ファイル名 (ダウンロード時に ZIP に含める対象)。
# v3/v4 で許容される .txt 一式。中間ファイルや入力 CSV/KML は含めない。
_GTFS_TXT_FILES = frozenset({
    "agency.txt", "stops.txt", "routes.txt", "trips.txt",
    "stop_times.txt", "calendar.txt", "calendar_dates.txt",
    "shapes.txt", "feed_info.txt", "fare_attributes.txt",
    "fare_rules.txt", "transfers.txt", "translations.txt",
    "attributions.txt", "frequencies.txt", "levels.txt",
    "pathways.txt",
})


@st.cache_resource
def get_agent():
    """エージェントをキャッシュして取得。"""
    return create_gtfs_agent()


def _init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "thread_id" not in st.session_state:
        st.session_state["thread_id"] = str(uuid.uuid4())
    if "pending_actions" not in st.session_state:
        st.session_state["pending_actions"] = None
    if "saved_uploads" not in st.session_state:
        st.session_state["saved_uploads"] = set()
    if "renaming_file" not in st.session_state:
        st.session_state["renaming_file"] = None


def _handle_response(response: AgentResponse) -> None:
    """invoke/resume の戻り値を session_state とチャット履歴に反映する。"""
    if response.status == "interrupt":
        st.session_state["pending_actions"] = response.pending_actions
        return

    # interrupt 以外は承認待ちを解除し、結果をチャットに追記
    st.session_state["pending_actions"] = None
    content = response.message or "(応答なし)"
    if response.status == "error":
        st.session_state["messages"].append(
            {"role": "assistant", "content": f"⚠ {content}"}
        )
    else:
        st.session_state["messages"].append(
            {"role": "assistant", "content": content}
        )


def _render_pending_action(idx: int, action: PendingAction) -> None:
    """1件の承認待ちアクションを表示する (ツール別の自然言語サマリ + 必要ならプレビュー)。"""
    label = tool_label(action.tool_name)
    st.markdown(f"#### {idx + 1}. {label}")

    # ツールごとに自然言語のサマリ (例: 「○○」から停留所マスタを作成します)。
    # 同じ arg key でもツールによって意味が違うので表組みより自然文の方が誤解が少ない。
    summary = tool_summary(action.tool_name, action.args or {})
    if summary:
        st.markdown(summary)
    elif action.args:
        # サマリテンプレが未定義のツールはフォールバックで簡易表示
        for k, v in action.args.items():
            display_v = "（未設定）" if v in (None, "") else str(v)
            st.markdown(f"- **{arg_label(k)}**: {display_v}")

    # stop_times 生成は確認層で「正規化後の時刻表」を見せる (本研究の三層構造の中核)。
    if action.tool_name == "generate_stop_times_from_csv":
        _render_stop_times_preview(action.args)


def _load_known_stop_names(stops_filename: str) -> set[str]:
    """stops.txt から stop_name 集合を読み込む (cross-file 整合性チェック用)。

    stops.txt が無ければ空集合 (= 警告を出さない、初期状態を許容)。
    GTFS 標準列順 (stop_id, stop_code, stop_name, stop_lat, stop_lon) を前提に
    3 列目を stop_name として読む。
    """
    stops_path = WORKSPACE_DIR / stops_filename
    if not stops_path.exists():
        return set()
    try:
        text = read_text_auto(stops_path)
    except UnicodeDecodeError:
        return set()
    known: set[str] = set()
    for line in text.splitlines()[1:]:
        cells = line.split(",")
        if len(cells) >= 3 and cells[2].strip():
            known.add(cells[2].strip())
    return known


def _find_unmatched_stop_names(
    normalized_csv: str, known: set[str]
) -> list[tuple[str, list[str]]]:
    """正規化済みの時刻表 CSV (1 列目が stop_name) から、known に無い停留所名を返す。

    各要素は (stop_name, 類似候補リスト) のタプル。類似候補は known の中で
    その名前を部分文字列として含むもの (例: 「椎田交番」 → 「椎田交番（上り）」)。
    類似候補があれば「親停留所/標柱の表記揺れ」、無ければ「真の登録漏れ」と
    利用者に区別を提示できる。
    """
    if not known:
        return []
    unmatched: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for line in normalized_csv.splitlines()[1:]:
        cells = line.split(",")
        if not cells:
            continue
        name = cells[0].strip()
        if name and name not in known and name not in seen:
            candidates = sorted(k for k in known if name in k or k in name)
            unmatched.append((name, candidates))
            seen.add(name)
    return unmatched


def _render_stop_times_preview(args: dict) -> None:
    """generate_stop_times_from_csv の確認画面に、normalize 後のテンプレ形式
    時刻表を表として表示する。利用者はここで「形式変換が正しいか」を確認できる。
    """
    input_filename = args.get("input_csv_filename", "")
    if not input_filename:
        return
    input_path = WORKSPACE_DIR / input_filename
    if not input_path.exists():
        st.warning(f"入力ファイルが見つかりません: {input_filename}")
        return

    try:
        sources = read_timetable_sources(input_path)
    except ValueError as e:
        st.warning(f"プレビュー失敗: {e}")
        return
    except Exception as e:  # noqa: BLE001
        st.warning(f"プレビュー読み込み失敗: {e}")
        return

    if not sources:
        st.info("プレビュー可能なシートがありません。")
        return

    st.markdown("##### 📊 変換後の時刻表 (確認用)")
    st.caption(
        "アプリが内部テンプレ形式に変換した結果です。"
        "列の対応や値の置換 (例: 東/西→e/w) に問題がなければ「実行する」を押してください。"
    )

    # stops.txt と照合するための既知停留所名セットを 1 回だけ読み込む
    known_stop_names = _load_known_stop_names(
        args.get("stops_filename", "stops.txt")
    )

    for name, text in sources:
        try:
            normalized = normalize_timetable(text)
        except ValueError as e:
            st.warning(f"[{name}] 正規化失敗: {e}")
            continue

        # cross-file 整合性チェック: stops.txt に登録されていない停留所名を可視化
        unmatched = _find_unmatched_stop_names(normalized, known_stop_names)
        if unmatched:
            # 「親停留所/標柱の表記揺れ」と「真の登録漏れ」を区別して提示
            similar = [(n, cands) for n, cands in unmatched if cands]
            missing = [n for n, cands in unmatched if not cands]

            st.error(
                f"⚠ [{name}] 時刻表に出てくる {len(unmatched)} 件の停留所が "
                "stops.txt に見つかりません"
            )
            if similar:
                st.markdown("**🔀 表記揺れの可能性 (停留所情報に類似名あり)** — "
                            "親停留所と標柱(乗り場)を分けた表記の差と思われます:")
                rows = ["| 時刻表の表記 | stops.txt に近い名前 |", "| :--- | :--- |"]
                for n, cands in similar[:8]:
                    cand_preview = "、".join(cands[:3])
                    if len(cands) > 3:
                        cand_preview += f" 他 {len(cands)-3} 件"
                    rows.append(f"| {n} | {cand_preview} |")
                if len(similar) > 8:
                    rows.append(f"| ...他 {len(similar)-8} 件 | |")
                st.markdown("\n".join(rows))
            if missing:
                preview = "、".join(missing[:5])
                more = "" if len(missing) <= 5 else f" 他 {len(missing)-5} 件"
                st.markdown(
                    f"**❌ 真の登録漏れ (停留所情報に該当なし)** ({len(missing)} 件): "
                    f"{preview}{more}"
                )
            st.caption(
                "実行時、プログラムは時刻表の stop_name で stops.txt を完全一致検索します。"
                "上記の停留所はその検索に失敗するので、生成される stop_times.txt の "
                "停留所ID (stop_id) 列が空欄になります (下の表ではなく出力ファイル側の話)。"
                "表記揺れであれば停留所情報側を統一するか、停留所情報を取り込み直してください。"
            )

        rows = [r.split(",") for r in normalized.split("\n") if r]
        if not rows:
            continue
        header = rows[0]
        data = rows[1:]
        # 列ごとの dict に組み替えて Streamlit にそのまま渡す (pandas は経由しない)
        max_cols = max(len(header), max((len(r) for r in data), default=0))
        # ヘッダ・データ行を欠損なく揃える
        header_padded = header + [""] * (max_cols - len(header))
        # 同名列があると dict が潰れるので、重複ヘッダには連番を振る
        seen: dict[str, int] = {}
        cols: list[str] = []
        for h in header_padded:
            base = h or "(無名)"
            if base in seen:
                seen[base] += 1
                cols.append(f"{base}#{seen[base]}")
            else:
                seen[base] = 1
                cols.append(base)
        table = {
            col: [
                (row[i] if i < len(row) else "")
                for row in data
            ]
            for i, col in enumerate(cols)
        }

        if len(sources) > 1:
            with st.expander(
                f"📋 {name} ({len(data)}行)", expanded=False
            ):
                st.dataframe(
                    table, use_container_width=True, hide_index=True
                )
        else:
            st.dataframe(
                table, use_container_width=True, hide_index=True
            )


def _render_confirmation_panel(actions: list[PendingAction]) -> None:
    """利用者確認層 UI: 承認待ちのツール一覧を表示し承認/拒否を受け付ける。"""
    st.warning(
        f"📋 次の操作を実行してよろしいですか？（{len(actions)}件）"
        "　内容を確認してから「実行する」を押してください。"
    )

    with st.container(border=True):
        for i, action in enumerate(actions):
            _render_pending_action(i, action)
            if i < len(actions) - 1:
                st.divider()

    col1, col2, _ = st.columns([1, 1, 2])
    if col1.button("✓ 実行する", type="primary", use_container_width=True):
        decisions = [{"type": "approve"} for _ in actions]
        agent = get_agent()
        with st.spinner("実行中..."):
            response = resume_agent(
                agent, decisions, st.session_state["thread_id"]
            )
        _handle_response(response)
        st.rerun()
    if col2.button("✗ やり直す", use_container_width=True):
        decisions = [
            {"type": "reject", "message": "利用者が拒否しました"}
            for _ in actions
        ]
        agent = get_agent()
        with st.spinner("処理中..."):
            response = resume_agent(
                agent, decisions, st.session_state["thread_id"]
            )
        _handle_response(response)
        st.rerun()


def _save_uploaded_files(uploaded) -> list[str]:
    """新規アップロードを workspace に保存し、保存したファイル名を返す。
    既に保存済みのものは再書き込みしない (Streamlit が rerun のたびに
    file_uploader の中身を返してくるため)。"""
    if not uploaded:
        return []
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    new_saves: list[str] = []
    for uf in uploaded:
        data = uf.getvalue()
        # name + size の組で簡易デデュープ
        key = (uf.name, len(data))
        if key in st.session_state["saved_uploads"]:
            continue
        (WORKSPACE_DIR / uf.name).write_bytes(data)
        st.session_state["saved_uploads"].add(key)
        new_saves.append(uf.name)
    return new_saves


def _next_timetable_filename() -> str:
    """次に使える「時刻表N.csv」を返す (N は 1 から始まり、未使用の最小値)。"""
    n = 1
    while (WORKSPACE_DIR / f"時刻表{n}.csv").exists():
        n += 1
    return f"時刻表{n}.csv"


def _save_pasted_timetable(text: str) -> str:
    """貼り付けられた時刻表テキストを workspace に CSV として保存し、ファイル名を返す。

    Excel からのコピーはタブ区切りで貼り付けられるので、タブをカンマに変換して
    そのまま CSV として扱う (元から CSV のテキストを貼られた場合も同じ処理で通る)。
    ファイル名は「時刻表1.csv」「時刻表2.csv」と連番。後で名前変更も可能。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(
        line.replace("\t", ",") for line in normalized.split("\n")
    )
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    filename = _next_timetable_filename()
    (WORKSPACE_DIR / filename).write_text(normalized, encoding="utf-8")
    return filename


def _rename_workspace_file(old_name: str, new_name: str) -> tuple[bool, str]:
    """workspace 内のファイルをリネーム。成功なら (True, 新名)、失敗なら (False, 理由)。

    安全のため:
    - パスセパレータ / 上位ディレクトリ参照は拒否
    - 既存ファイル名と衝突する場合は拒否
    - 元と同じ名前なら no-op
    """
    new_name = new_name.strip()
    if not new_name:
        return False, "ファイル名が空です"
    if "/" in new_name or "\\" in new_name or ".." in new_name:
        return False, "ファイル名にパス区切り文字や '..' は使えません"
    if new_name == old_name:
        return True, new_name
    old_path = WORKSPACE_DIR / old_name
    new_path = WORKSPACE_DIR / new_name
    if not old_path.exists():
        return False, "元のファイルが見つかりません"
    if new_path.exists():
        return False, f"「{new_name}」は既に存在します"
    old_path.rename(new_path)
    # アップロードのデデュープ記憶も同名分を更新 (再アップロード時に重複しないように)
    if "saved_uploads" in st.session_state:
        st.session_state["saved_uploads"] = {
            (new_name if key[0] == old_name else key[0], key[1])
            for key in st.session_state["saved_uploads"]
        }
    return True, new_name


def _delete_workspace_file(name: str) -> None:
    """workspace のファイルを削除し、アップロードのデデュープ記憶も同名分を消す。
    これにより、誤って削除しても同じファイルを再アップロードして復旧できる。"""
    path = WORKSPACE_DIR / name
    if path.exists():
        path.unlink()
    if "saved_uploads" in st.session_state:
        st.session_state["saved_uploads"] = {
            key
            for key in st.session_state["saved_uploads"]
            if key[0] != name
        }


def _build_gtfs_zip() -> bytes | None:
    """workspace の GTFS 標準ファイル (.txt) を ZIP にまとめて返す。
    GTFS フィードの納品形式 (zip) と同じ構造。揃っていなければ None。"""
    if not WORKSPACE_DIR.exists():
        return None
    txts = [
        p for p in WORKSPACE_DIR.iterdir()
        if p.is_file() and p.name in _GTFS_TXT_FILES
    ]
    if not txts:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in txts:
            zf.write(p, arcname=p.name)
    return buf.getvalue()


def _render_sidebar() -> None:
    """サイドバー: アップロード、作業中ファイル一覧、ダウンロード、その他。"""
    with st.sidebar:
        # アップロード ──────────────────────────
        st.markdown("### 📤 ファイルをアップロード")
        st.caption("元データ (時刻表 Excel・経路 KML 等) をここから取り込む")
        uploaded = st.file_uploader(
            "ファイル選択",
            accept_multiple_files=True,
            type=["xlsx", "xls", "csv", "kml", "txt"],
            label_visibility="collapsed",
        )
        new_saves = _save_uploaded_files(uploaded)
        if new_saves:
            st.success(
                "保存しました: " + ", ".join(f"`{n}`" for n in new_saves)
            )

        st.divider()

        # 時刻表を貼り付け ──────────────────────
        st.markdown("### 📋 時刻表を貼り付け")
        st.caption("Excel や CSV のセルを選択 → コピー → ここに貼り付けて保存")
        pasted = st.text_area(
            "貼り付け",
            height=150,
            placeholder=(
                "停留所名,方角,便1,便2,便3\n"
                "停留所A,東,08:05,08:35,09:05\n"
                "停留所B,西,08:10,08:40,09:10\n"
                "停留所C,北,08:15,08:45,09:15"
            ),
            label_visibility="collapsed",
            key="pasted_timetable_text",
        )
        if st.button(
            "時刻表として保存",
            use_container_width=True,
            disabled=not pasted.strip(),
        ):
            saved_name = _save_pasted_timetable(pasted)
            st.success(f"保存しました: `{saved_name}`")

        st.divider()

        # 作業中のファイル一覧 ─────────────────────
        st.markdown("### 📁 作成中のファイル")
        if WORKSPACE_DIR.exists():
            files = sorted(
                p.name for p in WORKSPACE_DIR.iterdir() if p.is_file()
            )
            # 内部用ファイル (_*, .* 等) は隠す
            shown = [f for f in files if not f.startswith(("_", "."))]
            if shown:
                renaming = st.session_state.get("renaming_file")
                for f in shown:
                    if renaming == f:
                        # 名前変更モード: 入力欄 + 保存/中止
                        ncol, scol, ccol = st.columns([4, 1, 1])
                        new_name = ncol.text_input(
                            "新ファイル名",
                            value=f,
                            label_visibility="collapsed",
                            key=f"rename_input_{f}",
                        )
                        if scol.button(
                            "✓", key=f"save_{f}", help="保存"
                        ):
                            ok, msg = _rename_workspace_file(f, new_name)
                            if not ok:
                                st.warning(msg)
                            st.session_state["renaming_file"] = None
                            st.rerun()
                        if ccol.button(
                            "↩", key=f"cancel_{f}", help="キャンセル"
                        ):
                            st.session_state["renaming_file"] = None
                            st.rerun()
                    else:
                        fcol, ecol, dcol = st.columns([4, 1, 1])
                        fcol.markdown(f"・{f}")
                        if ecol.button(
                            "✏", key=f"edit_{f}", help=f"{f} の名前を変更"
                        ):
                            st.session_state["renaming_file"] = f
                            st.rerun()
                        if dcol.button(
                            "✕", key=f"del_{f}", help=f"{f} を削除"
                        ):
                            _delete_workspace_file(f)
                            st.rerun()
            else:
                st.info("まだファイルはありません。")
        else:
            st.warning("作業フォルダが見つかりません。")

        st.divider()

        # GTFS ダウンロード ──────────────────────
        st.markdown("### 📥 GTFS データの取り出し")
        zip_data = _build_gtfs_zip()
        if zip_data:
            st.download_button(
                label="GTFS データを ZIP でダウンロード",
                data=zip_data,
                file_name="gtfs.zip",
                mime="application/zip",
                use_container_width=True,
                type="primary",
            )
            st.caption("このまま経路検索サービスへ提出する形式です")
        else:
            st.caption("GTFS ファイルがまだ揃っていません")

        st.divider()

        if st.button("会話をリセット", use_container_width=True):
            st.session_state["messages"] = []
            st.session_state["thread_id"] = str(uuid.uuid4())
            st.session_state["pending_actions"] = None
            st.session_state["saved_uploads"] = set()
            st.rerun()

        st.divider()

        with st.expander("このシステムについて"):
            st.markdown(
                """
                自治体担当者が GTFS-JP データを対話で作成できるよう支援します。

                **使い方:**
                1. 左のパネルから時刻表 Excel や経路 KML をアップロード
                2. チャットで「時刻表を取り込みたい」等を入力
                3. AI が抽出した内容を画面で確認 →「実行する」
                4. 完成したら「GTFS データを ZIP でダウンロード」

                **仕組み:**
                - 対話 AI が意図を解釈し、ツール選択
                - 各ファイルの作成はプログラムが決定論的に実行
                - 書き込み前に内容を画面で確認してから実行
                """
            )


def _render_output_previews() -> None:
    """生成済みの GTFS-JP ファイルを地図 / 表で表示する (出力確認層)。

    三層構造の人間層を「入力データの確認」だけでなく「出力結果の確認」に
    拡張する位置づけ。GTFS の仕様を知らない利用者でも、地図に経路が描画
    されることで「正しく作れているか」を視覚的に判断できる。
    """
    has_stops = (WORKSPACE_DIR / "stops.txt").exists()
    has_shapes = (WORKSPACE_DIR / "shapes.txt").exists()
    has_stop_times = (WORKSPACE_DIR / "stop_times.txt").exists()

    if not (has_stops or has_shapes or has_stop_times):
        return

    st.markdown("### 🗺 生成結果のプレビュー")
    st.caption(
        "生成された GTFS-JP ファイルを地図 / 表で確認できます。"
        "経路や停留所が地図上で意図通りに見えるかを利用者が判断するレイヤ。"
    )

    if has_stops:
        with st.expander(
            "📍 停留所 (stops.txt) — 地図とテーブル", expanded=False
        ):
            _render_stops_output_map()

    if has_shapes:
        with st.expander(
            "🛣 路線形状 (shapes.txt) — 地図", expanded=False
        ):
            _render_shapes_output_map()

    if has_stop_times:
        with st.expander(
            "⏰ 時刻表 (stop_times.txt) — テーブル", expanded=False
        ):
            _render_stop_times_output_table()


def _render_stops_output_map() -> None:
    """stops.txt の停留所を地図にマーカー表示 + テーブル表示。"""
    import pandas as pd

    try:
        df = pd.read_csv(
            WORKSPACE_DIR / "stops.txt", dtype=str, keep_default_na=False
        )
    except Exception as e:  # noqa: BLE001
        st.warning(f"stops.txt の読み込み失敗: {e}")
        return

    if "stop_lat" not in df.columns or "stop_lon" not in df.columns:
        st.warning("stop_lat / stop_lon 列が見つかりません。")
        return

    df["lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
    valid = df.dropna(subset=["lat", "lon"])
    invalid_count = len(df) - len(valid)

    msg = f"{len(valid)} 件の停留所を地図に表示"
    if invalid_count:
        msg += f" (緯度経度が空 / 無効の {invalid_count} 件は除外)"
    st.caption(msg)

    if len(valid) > 0:
        st.map(valid[["lat", "lon"]], zoom=11)

    st.markdown("##### 全データ (テーブル)")
    show_df = df.drop(columns=["lat", "lon"], errors="ignore")
    st.dataframe(
        show_df, use_container_width=True, hide_index=True, height=250
    )


def _render_shapes_output_map() -> None:
    """shapes.txt の経路を地図にライン表示 (shape_id ごとに色分け)。"""
    import pandas as pd
    import pydeck as pdk

    try:
        df = pd.read_csv(
            WORKSPACE_DIR / "shapes.txt", dtype=str, keep_default_na=False
        )
    except Exception as e:  # noqa: BLE001
        st.warning(f"shapes.txt の読み込み失敗: {e}")
        return

    needed = ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]
    if not all(c in df.columns for c in needed):
        st.warning(f"必要な列がありません: {needed}")
        return

    df["lat"] = pd.to_numeric(df["shape_pt_lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["shape_pt_lon"], errors="coerce")
    df["seq"] = pd.to_numeric(df["shape_pt_sequence"], errors="coerce")
    df = df.dropna(subset=["lat", "lon", "seq"])

    if df.empty:
        st.info("有効な座標を含む経路がありません。")
        return

    palette = [
        [220, 20, 60],
        [30, 144, 255],
        [50, 205, 50],
        [255, 140, 0],
        [186, 85, 211],
        [0, 139, 139],
        [255, 215, 0],
    ]
    shapes_data: list[dict] = []
    for i, (shape_id, group) in enumerate(df.groupby("shape_id")):
        sorted_group = group.sort_values("seq")
        path_coords = sorted_group[["lon", "lat"]].values.tolist()
        shapes_data.append(
            {
                "shape_id": str(shape_id),
                "path": path_coords,
                "color": palette[i % len(palette)],
            }
        )

    st.caption(f"{len(shapes_data)} 経路を表示 / 合計 {len(df)} 点")

    center_lat = float(df["lat"].mean())
    center_lon = float(df["lon"].mean())

    path_layer = pdk.Layer(
        "PathLayer",
        shapes_data,
        get_path="path",
        get_color="color",
        width_min_pixels=3,
        pickable=True,
    )
    view_state = pdk.ViewState(
        latitude=center_lat, longitude=center_lon, zoom=11
    )
    deck = pdk.Deck(
        layers=[path_layer],
        initial_view_state=view_state,
        tooltip={"text": "shape_id: {shape_id}"},
    )
    st.pydeck_chart(deck)

    # 凡例
    legend_parts = ["**凡例:**"]
    for s in shapes_data:
        r, g, b = s["color"]
        legend_parts.append(
            f"<span style='display:inline-block;width:18px;height:4px;"
            f"background-color:rgb({r},{g},{b});margin-right:6px;"
            f"vertical-align:middle;'></span>{s['shape_id']}"
        )
    st.markdown("　".join(legend_parts), unsafe_allow_html=True)


def _render_stop_times_output_table() -> None:
    """stop_times.txt を表で表示 (件数サマリ付き)。"""
    import pandas as pd

    try:
        df = pd.read_csv(
            WORKSPACE_DIR / "stop_times.txt",
            dtype=str,
            keep_default_na=False,
        )
    except Exception as e:  # noqa: BLE001
        st.warning(f"stop_times.txt の読み込み失敗: {e}")
        return

    n_rows = len(df)
    n_trips = df["trip_id"].nunique() if "trip_id" in df.columns else "?"
    n_stops = df["stop_id"].nunique() if "stop_id" in df.columns else "?"
    st.caption(
        f"{n_rows} 行 / {n_trips} 便 / {n_stops} 種の停留所 ID"
    )
    st.dataframe(
        df, use_container_width=True, hide_index=True, height=400
    )


def main() -> None:
    _init_state()
    _render_sidebar()

    st.title("GTFS-JP ChatBuilder")

    # 生成済み GTFS-JP ファイルのプレビュー (collapsed expander)
    _render_output_previews()

    # チャット履歴表示
    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # 利用者確認層: 承認待ちがあれば確認パネル、なければ通常入力
    if st.session_state.get("pending_actions"):
        _render_confirmation_panel(st.session_state["pending_actions"])
    else:
        if prompt := st.chat_input(
            "例: 時刻表を取り込みたい / 経路 KML を取り込みたい / 進捗を確認したい"
        ):
            st.session_state["messages"].append(
                {"role": "user", "content": prompt}
            )
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.spinner("処理中..."):
                agent = get_agent()
                response = invoke_agent(
                    agent, prompt, st.session_state["thread_id"]
                )
            _handle_response(response)
            st.rerun()


main()
