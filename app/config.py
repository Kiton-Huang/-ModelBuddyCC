"""
配置管理器 — 管理 .claude.json 读写 + 配置文件持久化
"""
import os
import json
import shutil
from datetime import datetime

from app.constants import (
    CLAUDE_JSON, CLAUDE_SETTINGS, PROFILES_FILE,
    LAUNCH_HISTORY_FILE, BACKUP_DIR,
)
from app.models import ModelProfile, LaunchRecord


class ConfigManager:
    """管理 .claude.json 的读写 + 配置文件的持久化"""

    @staticmethod
    def load_env() -> dict:
        """读取当前 .claude.json 中的 env 配置"""
        try:
            data = json.loads(CLAUDE_JSON.read_text(encoding="utf-8"))
            return data.get("env", {})
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @staticmethod
    def apply_env(env: dict) -> bool:
        """将 env 配置写回 .claude.json（保留其他字段）"""
        try:
            data = json.loads(CLAUDE_JSON.read_text(encoding="utf-8"))

            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(str(CLAUDE_JSON), str(BACKUP_DIR / f".claude.json.{ts}.bak"))

            # 只保留最新 5 个备份
            backups = sorted(BACKUP_DIR.glob(".claude.json.*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[5:]:
                old.unlink()

            data["env"] = env
            CLAUDE_JSON.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except Exception as e:
            print(f"应用配置失败: {e}")
            return False

    # ── 配置记忆 ──
    @staticmethod
    def load_profiles() -> list[ModelProfile]:
        if PROFILES_FILE.exists():
            try:
                raw = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
                return [ModelProfile.from_dict(p) for p in raw]
            except Exception:
                pass
        return []

    @staticmethod
    def save_profiles(profiles: list[ModelProfile]):
        PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROFILES_FILE.write_text(
            json.dumps([p.to_dict() for p in profiles], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 执行模式 (settings.json) ──
    @staticmethod
    def load_default_mode() -> str:
        """读取 settings.json 中的默认执行模式"""
        try:
            if CLAUDE_SETTINGS.exists():
                data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
                return data.get("permissions", {}).get("defaultMode", "default")
        except Exception:
            pass
        return "default"

    @staticmethod
    def save_default_mode(mode: str) -> bool:
        """将默认执行模式写入 settings.json（保留其他字段）"""
        try:
            data = {}
            if CLAUDE_SETTINGS.exists():
                data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))

            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(str(CLAUDE_SETTINGS), str(BACKUP_DIR / f"settings.json.{ts}.bak"))

            settings_backups = sorted(
                BACKUP_DIR.glob("settings.json.*.bak"),
                key=lambda p: p.stat().st_mtime, reverse=True
            )
            for old in settings_backups[5:]:
                old.unlink()

            if "permissions" not in data:
                data["permissions"] = {}
            data["permissions"]["defaultMode"] = mode

            CLAUDE_SETTINGS.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except Exception as e:
            print(f"保存执行模式失败: {e}")
            return False

    # ── 启动历史 ──
    @staticmethod
    def load_launch_history() -> list[LaunchRecord]:
        if LAUNCH_HISTORY_FILE.exists():
            try:
                raw = json.loads(LAUNCH_HISTORY_FILE.read_text(encoding="utf-8"))
                return [LaunchRecord.from_dict(r) for r in raw]
            except Exception:
                pass
        return []

    @staticmethod
    def save_launch_history(records: list[LaunchRecord]):
        LAUNCH_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_HISTORY_FILE.write_text(
            json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
