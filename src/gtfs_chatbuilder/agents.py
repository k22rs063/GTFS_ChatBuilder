"""GTFS 作成支援エージェント定義。

里村ツールの範囲 (stopTimesProcessor / shapesProcessor / kmlProcessor) に
合わせて、stop_times.txt と shapes.txt の作成のみを対象とする。
agency / feed_info / stops / routes 系のツールはソースとしては残しているが、
ここでは登録していない (LLM から呼び出せない / UI からも見えない)。

LLM の接続先は `.env` の以下 3 変数で指定する:
- LOCAL_BASE_URL (例: http://133.17.164.115:1234/v1 ← LM Studio)
- LOCAL_MODEL    (例: google/gemma-4-26b-a4b)
- LOCAL_API_KEY  (LM Studio は "not-used" でよい)

OpenAI 互換 API なら何でも使える (LM Studio / Ollama / vLLM / Gemini の OpenAI
互換層 / OpenAI 本体 / Together / DeepSeek 等)。未設定の場合は `_DEFAULT_*`
定数の値が使われる。
"""

import os

from langchain.agents import create_agent
from langchain.agents.middleware.human_in_the_loop import HumanInTheLoopMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from gtfs_chatbuilder.tools.kml import convert_kml_to_coordinates
from gtfs_chatbuilder.tools.project_status import get_project_status
from gtfs_chatbuilder.tools.shapes import generate_shapes_from_coordinates
from gtfs_chatbuilder.tools.stop_times import generate_stop_times_from_csv
from gtfs_chatbuilder.tools.stops import generate_stops_from_csv

# .env が未設定のときに使うフォールバック値。
_DEFAULT_LLM_BASE_URL = "http://133.17.164.115:1234/v1"
_DEFAULT_LLM_MODEL = "google/gemma-4-26b-a4b"
_DEFAULT_LLM_API_KEY = "not-used"

GTFS_AGENT_SYSTEM_PROMPT = """あなたはGTFS-JP v4 作成支援アシスタントです。
区役所担当者など、GTFSの知識がない自治体職員がチャットで時刻表データ
(stop_times.txt) と経路情報 (shapes.txt) を作っていけるよう支援することが
目的です。

# ツール呼び出しのルール (厳守)

ユーザーの発話に応じて、以下のいずれかのツールを必ず呼んでください。
ツールを呼ばずに「分かりません」「進捗を確認します」とだけ答えるのは禁止です。

## get_project_status
- 「進捗」「状況」「どこまで進んだ」「次に何を」を含む発話 → 必ずこのツールを呼ぶ
- 何か新しい入力作業を始める前 → 必ずこのツールを呼んで現状把握
- ツールの戻り値(JSON)を解釈して、ユーザーに分かりやすく日本語で要約する

## generate_stops_from_csv
- 「停留所を作って」「停留所情報を取り込みたい」「stops.txt を作って」→ このツールを呼ぶ
- 自治体の停留所一覧 CSV (バス停名 + 緯度経度 等を含むもの) から stops.txt を生成する
- 引数は workspace 内の CSV ファイル名。ファイル名が不明ならユーザーに質問する

## generate_stop_times_from_csv
- 「stop_times を作って」「時刻表からGTFSを作って」「時刻表を取り込みたい」→ このツールを呼ぶ
- 引数は workspace 内の CSV ファイル名。ファイル名が不明ならユーザーに質問する

## generate_shapes_from_coordinates
- 「shapes を作って」「座標から経路を作って」「経路情報を作りたい」→ このツールを呼ぶ
- 引数は shape_id と workspace 内の座標テキストファイル名。不足していたら質問する

## convert_kml_to_coordinates
- 「KMLから座標を抽出」「KMLを変換」「経路の KML を取り込みたい」→ このツールを呼ぶ
- shapes.txt を作る前段として、Google マイマップ等から書き出した KML を座標テキストに変換する
- 引数は workspace 内の KML ファイル名

# 重要な原則

- ファイルに書き込まれる値(座標、時刻、停留所名、読み仮名など)を自分で生成しない
- ユーザーが提供していない情報は推測せず、ユーザーに質問する
- ファイル名や引数はユーザー発話から抽出するだけにする

必ず日本語で対応してください。
""".strip()


def create_gtfs_agent():
    """GTFS 作成支援エージェントを作成する。

    LLM 接続先は `.env` の LOCAL_BASE_URL / LOCAL_MODEL / LOCAL_API_KEY を
    読む。未設定なら `_DEFAULT_*` 定数を使う。`.env` の読み込みは呼び出し側
    (app.py 等) が事前に行っている前提。
    """
    base_url = os.environ.get("LOCAL_BASE_URL", _DEFAULT_LLM_BASE_URL)
    model_name = os.environ.get("LOCAL_MODEL", _DEFAULT_LLM_MODEL)
    api_key = os.environ.get("LOCAL_API_KEY", _DEFAULT_LLM_API_KEY)

    llm = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        temperature=0.1,
    )

    # 利用者確認層: 書き込み系ツールは実行前に利用者の承認を必要とする。
    # get_project_status は読み取り専用なので auto-approve (interrupt_on に含めない)。
    interrupt_on = {
        "generate_stops_from_csv": True,
        "generate_stop_times_from_csv": True,
        "generate_shapes_from_coordinates": True,
        "convert_kml_to_coordinates": True,
    }

    return create_agent(
        model=llm,
        tools=[
            get_project_status,
            generate_stops_from_csv,
            generate_stop_times_from_csv,
            generate_shapes_from_coordinates,
            convert_kml_to_coordinates,
        ],
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on=interrupt_on,
                description_prefix="このツールを実行する前に内容を確認してください",
            ),
        ],
        system_prompt=GTFS_AGENT_SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )
