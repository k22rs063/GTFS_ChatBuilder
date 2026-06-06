"""進捗メタファイル (.gtfs_progress.json) の読み書きと、
各ステップの状態を表すデータクラス。

設計指針:
- メタファイルは workspace/ 直下に置く
- 状態はフィールド単位で追跡 (粒度: design_state_management.md)
- 各ステップは pending/in_progress/completed/optional_pending/error
- メタファイルと実ファイルの整合性は validators 側で確認
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

from gtfs_chatbuilder.paths import WORKSPACE_DIR

PROGRESS_FILENAME = ".gtfs_progress.json"
GTFS_JP_VERSION = "4.0"

# Phase 1 で扱うステップ名 (GTFS-JP v4 ファイル名と対応)
STEP_NAMES: tuple[str, ...] = (
    "feed_info",
    "agency",
    "stops",
    "translations",
    "routes",
    "trips",
    "stop_times",
    "calendar",
    "calendar_dates",
    "fare_attributes",
    "fare_rules",
    "shapes",
    "attributions",
    "transfers",
)

# 任意・条件付必須のステップ (デフォルトで optional_pending)
OPTIONAL_STEPS: frozenset[str] = frozenset(
    {"shapes", "attributions", "transfers", "calendar_dates", "fare_rules"}
)


@dataclass
class StepProgress:
    """1つの GTFS ファイル/ステップに対応する進捗。"""

    name: str
    status: str = "pending"  # pending|in_progress|completed|optional_pending|error
    source_files: list[str] = field(default_factory=list)
    fields_set: list[str] = field(default_factory=list)
    fields_missing: list[str] = field(default_factory=list)
    # translations 専用カウンタ (design_translations.md)
    auto_generated: int = 0
    user_confirmed: int = 0
    total: int = 0


@dataclass
class ProjectProgress:
    """プロジェクト全体の進捗メタデータ。"""

    name: str = ""
    created_at: str = ""
    updated_at: str = ""
    gtfs_jp_version: str = GTFS_JP_VERSION
    steps: dict[str, StepProgress] = field(default_factory=dict)

    @classmethod
    def new(cls, project_name: str = "") -> ProjectProgress:
        """空の状態でプロジェクトを初期化する。"""
        now = _now_iso()
        steps: dict[str, StepProgress] = {}
        for name in STEP_NAMES:
            initial = "optional_pending" if name in OPTIONAL_STEPS else "pending"
            steps[name] = StepProgress(name=name, status=initial)
        return cls(
            name=project_name,
            created_at=now,
            updated_at=now,
            steps=steps,
        )

    def to_dict(self) -> dict:
        return {
            "project": {
                "name": self.name,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "gtfs_jp_version": self.gtfs_jp_version,
            },
            "steps": {name: asdict(step) for name, step in self.steps.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectProgress:
        project_meta = data.get("project", {})
        steps_data = data.get("steps", {})

        steps: dict[str, StepProgress] = {}
        for name in STEP_NAMES:
            raw = steps_data.get(name)
            if raw is None:
                initial = "optional_pending" if name in OPTIONAL_STEPS else "pending"
                steps[name] = StepProgress(name=name, status=initial)
            else:
                steps[name] = StepProgress(
                    name=raw.get("name", name),
                    status=raw.get("status", "pending"),
                    source_files=list(raw.get("source_files", [])),
                    fields_set=list(raw.get("fields_set", [])),
                    fields_missing=list(raw.get("fields_missing", [])),
                    auto_generated=int(raw.get("auto_generated", 0)),
                    user_confirmed=int(raw.get("user_confirmed", 0)),
                    total=int(raw.get("total", 0)),
                )

        return cls(
            name=project_meta.get("name", ""),
            created_at=project_meta.get("created_at", _now_iso()),
            updated_at=project_meta.get("updated_at", _now_iso()),
            gtfs_jp_version=project_meta.get("gtfs_jp_version", GTFS_JP_VERSION),
            steps=steps,
        )

    def touch(self) -> None:
        """updated_at を現在時刻に更新する。"""
        self.updated_at = _now_iso()


def _now_iso() -> str:
    """JST の ISO 8601 文字列を返す。"""
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).replace(microsecond=0).isoformat()


def _progress_path(workspace: Path | None = None) -> Path:
    base = workspace if workspace is not None else WORKSPACE_DIR
    return base / PROGRESS_FILENAME


def load_progress(workspace: Path | None = None) -> ProjectProgress:
    """メタファイルを読み込む。なければ初期化したものを返す (ディスクには書かない)。"""
    path = _progress_path(workspace)
    if not path.exists():
        return ProjectProgress.new()

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 壊れていたら初期化して返す (上書き保存は呼び出し側の判断)
        return ProjectProgress.new()

    return ProjectProgress.from_dict(data)


def save_progress(progress: ProjectProgress, workspace: Path | None = None) -> None:
    """メタファイルを保存する。updated_at を自動更新する。"""
    progress.touch()
    path = _progress_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(progress.to_dict(), f, ensure_ascii=False, indent=2)
