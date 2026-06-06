"""エージェント呼び出しのラッパー (利用者確認層対応)。

create_agent 側に HumanInTheLoopMiddleware を組み込んであるため、
書き込み系ツール呼び出しの直前に interrupt が走る。invoke_agent は
- success: 通常のテキスト応答が返った
- interrupt: ツール承認待ち (pending_actions に詳細)
- error: 例外
のいずれかを返す。承認/拒否の決定は resume_agent で送り続行する。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

# ストリーミング時のイベント種別 (UI 側で分岐用)
StreamEvent = tuple[
    Literal["reasoning", "text", "done"],
    "str | AgentResponse",
]


@dataclass
class PendingAction:
    """利用者確認層が承認待ちで提示する単一の動作。"""

    tool_name: str
    args: dict[str, Any]
    description: str = ""


@dataclass
class AgentResponse:
    """エージェント対話の結果。"""

    status: Literal["success", "error", "interrupt"]
    message: str | None = None
    pending_actions: list[PendingAction] = field(default_factory=list)


def _extract_text(message: AIMessage) -> str | None:
    """AIMessage から表示用テキストを取り出す。"""
    content = message.content
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        text_parts = [
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if text_parts:
            return "".join(text_parts)
    return None


def _extract_text_from_result(result: dict) -> str | None:
    """実行結果から最後の AIMessage の表示用テキストを取り出す。
    取れなければ None (= 空応答)。"""
    if not isinstance(result, dict) or "messages" not in result:
        return None
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            text = _extract_text(msg)
            if text:
                return text
    return None


def _extract_pending_actions(result: dict) -> list[PendingAction]:
    """interrupt が発生した場合、承認待ちのアクション一覧を取り出す。"""
    if not isinstance(result, dict):
        return []
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return []
    pending: list[PendingAction] = []
    for irq in interrupts:
        # Interrupt オブジェクト (.value) または素の dict のどちらでも対応
        hitl = getattr(irq, "value", None)
        if hitl is None:
            hitl = irq if isinstance(irq, dict) else None
        if not isinstance(hitl, dict):
            continue
        for action_req in hitl.get("action_requests", []):
            pending.append(
                PendingAction(
                    tool_name=action_req.get("name", "<unknown>"),
                    args=action_req.get("args", {}),
                    description=action_req.get("description", ""),
                )
            )
    return pending


EMPTY_RESPONSE_FALLBACK = (
    "LLM から応答が返りませんでした(リトライも失敗)。"
    "「会話をリセット」ボタンを押してから再試行するか、"
    "GEMINI_MODEL を gemini-1.5-flash 等に切り替えて Streamlit を再起動してください。"
)


def invoke_agent(agent, user_message: str, thread_id: str) -> AgentResponse:
    """エージェントにメッセージを送り、応答を取り出す。

    書き込み系ツール呼び出し前に interrupt がかかった場合、
    AgentResponse.status="interrupt" + pending_actions を返す。
    """
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_message}]},
            config=config,
        )
    except Exception as e:  # noqa: BLE001 - 現状は LLM 由来の例外を網羅的に拾う
        return AgentResponse(status="error", message=f"エラーが発生しました: {e}")

    pending = _extract_pending_actions(result)
    if pending:
        return AgentResponse(status="interrupt", pending_actions=pending)

    text = _extract_text_from_result(result)
    if text:
        return AgentResponse(status="success", message=text)

    # 空応答リトライ: 明示的な指示で1回だけ再試行
    retry_prompt = (
        f"{user_message}\n\n"
        "(システム注記: 直前の応答が空でした。利用可能なツールを使うか、"
        "テキストで回答してください)"
    )
    try:
        retry_result = agent.invoke(
            {"messages": [{"role": "user", "content": retry_prompt}]},
            config=config,
        )
    except Exception as e:  # noqa: BLE001
        return AgentResponse(status="error", message=f"リトライ時にエラー: {e}")

    retry_pending = _extract_pending_actions(retry_result)
    if retry_pending:
        return AgentResponse(status="interrupt", pending_actions=retry_pending)

    retry_text = _extract_text_from_result(retry_result)
    if retry_text:
        return AgentResponse(status="success", message=retry_text)

    return AgentResponse(status="success", message=EMPTY_RESPONSE_FALLBACK)


def _iter_message_chunk(chunk) -> Iterator[StreamEvent]:
    """AIMessageChunk から (reasoning / text) イベントを取り出す。

    reasoning_content は DeepSeek R1 や OpenAI o-series のような推論モデルが
    streaming delta の `additional_kwargs.reasoning_content` に乗せて返してくる。
    Gemma 等の通常モデルでは reasoning は出ないので、その場合は何も yield しない。
    """
    additional = getattr(chunk, "additional_kwargs", {}) or {}
    reasoning = additional.get("reasoning_content")
    if reasoning:
        yield ("reasoning", reasoning)
    content = getattr(chunk, "content", None)
    if not content:
        return
    if isinstance(content, str):
        yield ("text", content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    yield ("text", text)


def _stream_agent(
    agent,
    input_payload,
    thread_id: str,
    error_prefix: str = "エラーが発生しました",
) -> Iterator[StreamEvent]:
    """agent.stream を多モード ("messages" + "updates") で回し、
    LLM トークンをリアルタイムに、interrupt は確実に拾うジェネレータ。
    最後に必ず ("done", AgentResponse) を 1 回 yield する。
    """
    config = {"configurable": {"thread_id": thread_id}}
    pending: list[PendingAction] = []
    try:
        for stream_mode, payload in agent.stream(
            input_payload,
            config=config,
            stream_mode=["messages", "updates"],
        ):
            if stream_mode == "messages":
                # payload は (AIMessageChunk, metadata) のタプル
                chunk = payload[0] if isinstance(payload, tuple) else payload
                yield from _iter_message_chunk(chunk)
            elif stream_mode == "updates":
                # ノード更新イベント。__interrupt__ が来ることがある
                if isinstance(payload, dict) and "__interrupt__" in payload:
                    found = _extract_pending_actions(payload)
                    if found:
                        pending = found
    except Exception as e:  # noqa: BLE001
        yield ("done", AgentResponse(status="error", message=f"{error_prefix}: {e}"))
        return

    if pending:
        yield ("done", AgentResponse(status="interrupt", pending_actions=pending))
        return

    # 最終状態から表示用テキストを取得 (ストリーミングで全文が来ない場合の保険)
    try:
        state = agent.get_state(config).values
    except Exception:  # noqa: BLE001
        state = None
    text = _extract_text_from_result(state) if state else None
    yield ("done", AgentResponse(status="success", message=text or "(応答なし)"))


def invoke_agent_stream(
    agent, user_message: str, thread_id: str
) -> Iterator[StreamEvent]:
    """invoke_agent のストリーミング版。reasoning と text を逐次 yield する。"""
    yield from _stream_agent(
        agent,
        {"messages": [{"role": "user", "content": user_message}]},
        thread_id,
    )


def resume_agent_stream(
    agent, decisions: list[dict], thread_id: str
) -> Iterator[StreamEvent]:
    """resume_agent のストリーミング版。"""
    yield from _stream_agent(
        agent,
        Command(resume={"decisions": decisions}),
        thread_id,
        error_prefix="承認処理でエラー",
    )


def resume_agent(agent, decisions: list[dict], thread_id: str) -> AgentResponse:
    """利用者の決定で interrupt 状態のエージェントを続行する。

    decisions は HumanInTheLoopMiddleware の Decision 一覧。
    例:
        [{"type": "approve"}]                                              # 承認
        [{"type": "reject", "message": "..."}]                             # 拒否
        [{"type": "edit", "edited_action": {"name": ..., "args": {...}}}]  # 編集
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = agent.invoke(
            Command(resume={"decisions": decisions}),
            config=config,
        )
    except Exception as e:  # noqa: BLE001
        return AgentResponse(status="error", message=f"承認処理でエラー: {e}")

    pending = _extract_pending_actions(result)
    if pending:
        return AgentResponse(status="interrupt", pending_actions=pending)

    text = _extract_text_from_result(result)
    if text:
        return AgentResponse(status="success", message=text)
    return AgentResponse(status="success", message="(承認後の応答なし)")
