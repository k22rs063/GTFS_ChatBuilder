"""プロジェクトの進捗状況を返すツール。

LLM が「次に何を促すべきか」「致命的な残課題はないか」を判断するための、
読み取り専用ツール。設計指針は design_validation.md。

今年度スコープに合わせて、里村ツール範囲 (shapes.txt / stop_times.txt) のみを
対象とする。agency / feed_info / stops / routes / trips / calendar / translations
等は内部の validator/progress には残っているが、本ツールの出力からは除外する。

返却内容:
- summary: 全体サマリ (X/Y ステップ完了)
- next_recommended: LLM が次に提案すべきアクション
- blockers: zip化を阻む致命的エラー
- warnings: zip化はできるが警告レベル
- steps: 各ステップの現在のステータス
"""

from __future__ import annotations

import json

from langchain.tools import tool

from gtfs_chatbuilder.paths import WORKSPACE_DIR
from gtfs_chatbuilder.progress import (
    STEP_NAMES,
    ProjectProgress,
    load_progress,
    save_progress,
)
from gtfs_chatbuilder.validators import validate_all
from gtfs_chatbuilder.validators.base import ValidationResult

# 今年度スコープ: 里村ツール範囲 (shapes.txt と stop_times.txt) のみ。
# get_project_status の summary / steps / blockers / warnings / next_recommended
# はすべてこの集合でフィルタする。
REQUIRED_STEPS: frozenset[str] = frozenset({"stop_times", "shapes"})


@tool
def get_project_status() -> str:
    """GTFS-JP v4 プロジェクトの現在の進捗状況を返す。

    LLM はこのツールで現状を把握してから、ユーザーに次のアクションを案内すること。
    トークン節約のため、ユーザーが「進捗を見たい」「次に何をすればいい?」のように
    尋ねたとき、または zip 化前の確認時に呼ぶ。

    Returns:
        プロジェクトの進捗を表す JSON 文字列。フィールド:
        - summary: 全体サマリ
        - next_recommended: 次のアクション提案
        - blockers: zip化を阻む致命的エラーのリスト
        - warnings: 警告のリスト
        - steps: 各ステップの状態 (completed/in_progress/pending/optional_pending/error)
    """
    progress = load_progress()
    validation_results = validate_all(WORKSPACE_DIR)
    _merge_validation_into_progress(progress, validation_results)
    save_progress(progress)

    summary_text = _build_summary(progress, validation_results)
    blockers, warnings = _collect_issues(validation_results)
    next_action = _suggest_next_action(progress, validation_results)
    # スコープ内のステップのみ報告 (STEP_NAMES の順序を保つ)
    steps_status = {
        name: progress.steps[name].status
        for name in STEP_NAMES
        if name in REQUIRED_STEPS and name in progress.steps
    }

    payload = {
        "summary": summary_text,
        "next_recommended": next_action,
        "blockers": blockers,
        "warnings": warnings,
        "steps": steps_status,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _merge_validation_into_progress(
    progress: ProjectProgress,
    results: dict[str, ValidationResult],
) -> None:
    """バリデーション結果をメタファイル側 (StepProgress) に反映する。"""
    for name, result in results.items():
        step = progress.steps.get(name)
        if step is None:
            continue
        step.status = result.status
        # 既存の fields_set/missing を上書き (validator が真実の情報源)
        step.fields_set = list(result.fields_set)
        step.fields_missing = list(result.fields_missing)


def _build_summary(
    progress: ProjectProgress, results: dict[str, ValidationResult]
) -> str:
    """スコープ内 (REQUIRED_STEPS) の完了数と致命的エラー数のサマリを返す。"""
    completed_required = sum(
        1
        for name in REQUIRED_STEPS
        if results.get(name) and results[name].status == "completed"
    )
    total_required = len(REQUIRED_STEPS)
    blocker_count = sum(
        len(r.blockers) for name, r in results.items() if name in REQUIRED_STEPS
    )
    return (
        f"必須ステップ進捗: {completed_required}/{total_required} 完了 / "
        f"致命的エラー: {blocker_count}件"
    )


def _collect_issues(
    results: dict[str, ValidationResult],
) -> tuple[list[str], list[str]]:
    """スコープ内 (REQUIRED_STEPS) のステップに限定して blockers/warnings を収集する。"""
    blockers: list[str] = []
    warnings: list[str] = []
    for name, result in results.items():
        if name not in REQUIRED_STEPS:
            continue
        blockers.extend(result.blockers)
        warnings.extend(result.warnings)
    return blockers, warnings


def _suggest_next_action(
    progress: ProjectProgress, results: dict[str, ValidationResult]
) -> str:
    """スコープ内 (shapes → stop_times) の順で、未完了の最初のステップを提案する。"""
    # shapes を先に作っておくと stop_times の shape_id 連携が楽 (依存順)。
    suggestion_order = ["shapes", "stop_times"]

    for name in suggestion_order:
        result = results.get(name)
        if result is None:
            continue
        if result.status == "pending":
            return f"{name} が未着手です。担当ツール経由で入力を開始してください。"
        if result.status == "in_progress":
            missing = (
                ", ".join(result.fields_missing)
                if result.fields_missing
                else "詳細未充足"
            )
            return f"{name} が進行中です。不足: {missing}"
        if result.status == "error":
            return f"{name} にエラーがあります: {'; '.join(result.blockers)}"

    return "全ステップ完了。zip 化が可能です。"
