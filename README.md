# GTFS-JP ChatBuilder

GTFS-JP (shapes.txt / stop_times.txt) を、LLM との対話で作れるかを
検証するプロトタイプ。先行研究 GTFS_WebBuilder (里村, 2026) の処理を
Python に移植し、LangChain ツールから呼び出す構成。

## 目的

Streamlit + LangChain + ChatOpenAI (OpenAI 互換 API) で、利用者が
GTFS の仕様用語を学ばずにチャットで「時刻表を取り込んで」「経路を
作って」と話すだけで GTFS-JP データが作れる体験を試す。

LLM はルーター層として動くだけで、ファイルに書き込まれる内容は
すべてプログラムが決定論的に生成する (ハルシネーション余地ゼロ)。
書き込み系ツール実行前には利用者確認層が介在する。

## 構成

```
GTFS_ChatBuilder/
├── pyproject.toml
├── .env                                ← LLM 接続先 (LOCAL_BASE_URL 等)
├── run.py                              ← Streamlit 起動
├── src/
│   └── gtfs_chatbuilder/
│       ├── app.py                      ← Streamlit エントリ (UI / 確認層)
│       ├── agents.py                   ← create_agent + HumanInTheLoopMiddleware
│       ├── controllers.py              ← invoke_agent / resume_agent
│       ├── paths.py                    ← PROJECT_ROOT, WORKSPACE_DIR
│       ├── friendly_names.py           ← ツール/引数の日本語ラベル
│       ├── progress/                   ← 進捗メタ (.gtfs_progress.json)
│       ├── validators/                 ← shapes/stop_times バリデータ
│       ├── processors/                 ← 決定論ファイル生成 (JS 由来を移植)
│       │   ├── stop_times.py           ← 旧/ewns/列グループ化/便+オプション 対応
│       │   ├── shapes.py               ← 経度9桁/緯度8桁ゼロ埋め
│       │   └── kml.py                  ← LineString/Polygon/gx:Track 対応
│       └── tools/
│           ├── stop_times.py           ← @tool: xlsx/csv 入力対応
│           ├── shapes.py               ← @tool: shapes.txt 生成
│           ├── kml.py                  ← @tool: KML→座標テキスト変換
│           └── project_status.py       ← @tool: 進捗確認 (読み取り専用)
└── workspace/                          ← GTFS ファイル置き場
```

## 動かし方

### 前提

- Python 3.12+
- OpenAI 互換 API のエンドポイント (LM Studio / Ollama / vLLM / Gemini の OpenAI 互換層 / OpenAI 本体 等のいずれか)

### セットアップ

```powershell
# 1. Python 仮想環境を作って依存をインストール
cd C:\Users\User\GTFS\GTFS_ChatBuilder
uv sync   # or: python -m venv .venv && .\.venv\Scripts\Activate.ps1 && pip install -e .

# 2. .env を編集
#    LOCAL_BASE_URL  例: http://localhost:1234/v1   (LM Studio)
#    LOCAL_MODEL     例: google/gemma-4-26b-a4b
#    LOCAL_API_KEY   例: not-used                    (LM Studio は任意文字列で可)

# 3. 起動
python run.py
```

ブラウザが開いたら、左サイドバーから時刻表 (xlsx / csv) や経路 KML を
アップロードまたは貼り付け → チャット入力欄から各ツールを呼び出す:

- `時刻表を取り込んで` → 取り込み元ファイルを聞かれて指定 → 確認画面で OK
- `route.kml から座標を抽出して` → `shape_1 で shapes.txt を作って` の順で経路作成

## 動作確認したいこと (本プロトタイプの検証目的)

1. LangChain の `@tool` 経由でファイル生成が走る
2. ツール docstring だけで LLM が適切にツールを選ぶ
3. 不足情報があるとき LLM がユーザーに聞く (=ハルシネートしてファイル名や座標を作らない)
4. 書き込み系ツール実行前に **利用者確認層** で内容を確認できる (`HumanInTheLoopMiddleware`)

## 既知の制限

- 入力形式 (時刻表) は里村ツールと同形式 (`stop_name` で始まるヘッダ) 前提。
  日本語ヘッダ (停留所名 / 方角 等) の自動別名対応は未実装
- 1 シートに往路と復路が両方入った xlsx は分割できない (Phase 2 課題)
- 標柱識別 (`_w` / `_e` 等の値変換) は未実装 (Phase 2 課題)
- Streamlit セッション状態は memory のみ。再起動で会話履歴は消える
  (ただし `workspace/` のファイルは消えない)
