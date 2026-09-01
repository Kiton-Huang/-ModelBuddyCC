"""
路径常量 & 执行模式定义
"""
import os
from pathlib import Path

# ─── 路径常量 ───────────────────────────────────────────────
CLAUDE_JSON = Path(os.path.expanduser("~/.claude.json"))
CLAUDE_SETTINGS = Path(os.path.expanduser("~/.claude/settings.json"))
PROFILES_FILE = Path(os.path.expanduser("~/.claude/model_profiles.json"))
LAUNCH_HISTORY_FILE = Path(os.path.expanduser("~/.claude/launch_history.json"))
BACKUP_DIR = Path(os.path.expanduser("~/.claude/backups"))
TRANSCRIPTS_DIR = Path(os.path.expanduser("~/.claude/projects"))

# ─── 通知相关 ─────────────────────────────────────────────
NOTIFY_SETTINGS_FILE = Path(os.path.expanduser("~/.claude/notify_settings.json"))
NOTIFY_EVENTS_DIR = Path(os.path.expanduser("~/.claude/modelbuddy_events"))
NOTIFY_SOUNDS_DIR = Path(os.path.expanduser("~/.claude/modelbuddy/sounds"))

# ─── 执行模式定义 ──────────────────────────────────────────────
EXECUTION_MODES = {
    "default": {
        "label": "默认模式 (Normal)",
        "desc": "每次操作都需要手动确认，最安全",
    },
    "acceptEdits": {
        "label": "编辑模式 (Accept Edits)",
        "desc": "自动接受文件编辑，Bash 命令仍需确认",
    },
    "plan": {
        "label": "计划模式 (Plan)",
        "desc": "仅分析和制定计划，不执行任何修改",
    },
    "dontAsk": {
        "label": "锁定模式 (Don't Ask)",
        "desc": "拒绝所有未授权操作，适合审查环境",
    },
    "auto": {
        "label": "自动模式 (Auto)",
        "desc": "AI 安全分类器实时把关，自动执行安全操作、拦截危险行为 — 即 Shift+Tab 切到的模式",
    },
    "bypassPermissions": {
        "label": "绕过模式 (Bypass)",
        "desc": "完全跳过所有权限检查，无安全防护，仅适合隔离沙盒环境",
    },
}
EXECUTION_MODE_KEYS = list(EXECUTION_MODES.keys())

# ─── 努力级别定义 ───────────────────────────────────────────
EFFORT_LEVELS = {
    "":       {"label": "默认",         "desc": "使用 Claude Code 默认努力级别"},
    "min":    {"label": "最低 (Min)",    "desc": "最小努力，响应最快"},
    "low":    {"label": "低 (Low)",      "desc": "较低努力"},
    "medium": {"label": "中 (Medium)",   "desc": "中等努力，平衡速度与深度"},
    "high":   {"label": "高 (High)",     "desc": "高努力，更深入分析"},
    "max":    {"label": "最大 (Max)",     "desc": "最大努力，最深度思考 — DeepSeek 推荐"},
}
EFFORT_LEVEL_KEYS = list(EFFORT_LEVELS.keys())
