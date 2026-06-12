"""
ModelBuddyCC — Claude Code 模型配置管理器
一键切换 .claude.json 中的 env 配置（API地址、密钥、模型名）
支持多配置记忆与快速切换
"""

import os
import json
import shutil
import ssl
import subprocess
import threading
import time
import html as _html
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

import customtkinter as ctk
from tkinter import messagebox, filedialog

# ─── 路径常量 ───────────────────────────────────────────────
CLAUDE_JSON = Path(os.path.expanduser("~/.claude.json"))
CLAUDE_SETTINGS = Path(os.path.expanduser("~/.claude/settings.json"))
PROFILES_FILE = Path(os.path.expanduser("~/.claude/model_profiles.json"))
LAUNCH_HISTORY_FILE = Path(os.path.expanduser("~/.claude/launch_history.json"))
BACKUP_DIR = Path(os.path.expanduser("~/.claude/backups"))
TRANSCRIPTS_DIR = Path(os.path.expanduser("~/.claude/projects"))

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

# ─── 主题配置 ───────────────────────────────────────────────
ctk.set_appearance_mode("system")
ctk.set_default_color_theme("dark-blue")

FONT_FAMILY = "Microsoft YaHei"

DARK_COLORS = {
    "bg_dark": "#0f1117",
    "bg_card": "#161822",
    "bg_hover": "#1e2130",
    "bg_input": "#1a1c26",
    "accent": "#6366f1",
    "accent_hover": "#5558e6",
    "accent_light": "#818cf8",
    "success": "#10b981",
    "success_hover": "#059669",
    "danger": "#f43f5e",
    "danger_hover": "#e11d48",
    "warning": "#f59e0b",
    "warning_hover": "#d97706",
    "text_primary": "#e2e8f0",
    "text_secondary": "#94a3b8",
    "text_muted": "#64748b",
    "border": "#1e293b",
    "border_active": "#6366f1",
}

LIGHT_COLORS = {
    "bg_dark": "#e2e5ea",
    "bg_card": "#ffffff",
    "bg_hover": "#dde1e7",
    "bg_input": "#eceff4",
    "accent": "#6366f1",
    "accent_hover": "#5558e6",
    "accent_light": "#4f46e5",
    "success": "#10b981",
    "success_hover": "#059669",
    "danger": "#ef4444",
    "danger_hover": "#dc2626",
    "warning": "#d97706",
    "warning_hover": "#b45309",
    "text_primary": "#0f172a",
    "text_secondary": "#334155",
    "text_muted": "#475569",
    "border": "#c8cdd5",
    "border_active": "#6366f1",
}

# 当前生效的颜色字典
COLORS: dict = {}
_appearance_mode: str = ""

def _init_colors():
    """根据当前系统外观初始化 COLORS"""
    global _appearance_mode
    _appearance_mode = ctk.get_appearance_mode().lower()
    if _appearance_mode == "dark":
        COLORS.update(DARK_COLORS)
    else:
        COLORS.update(LIGHT_COLORS)

def _sync_colors() -> bool:
    """检测系统外观变化并更新 COLORS，返回是否变化"""
    global _appearance_mode
    mode = ctk.get_appearance_mode().lower()
    if mode != _appearance_mode:
        _appearance_mode = mode
        COLORS.clear()
        if mode == "dark":
            COLORS.update(DARK_COLORS)
        else:
            COLORS.update(LIGHT_COLORS)
        return True
    return False

# 启动时立即初始化
_init_colors()


# ─── 余额查询 ──────────────────────────────────────────────────
def _parse_deepseek_balance(data: dict) -> str:
    infos = data.get("balance_infos", [])
    if infos:
        info = infos[0]
        total = info.get("total_balance", "?")
        currency = info.get("currency", "CNY")
        return f"{total} {currency}"
    return "未知"


def _parse_kimi_balance(data: dict) -> str:
    d = data.get("data", data)
    # Kimi 返回字段可能是 available_balance / total_balance / balance，按优先级尝试
    for key in ("available_balance", "total_balance", "balance"):
        val = d.get(key)
        if val is not None and val != "":
            return f"{val} 元"
    return "未知"


# 注册表：域名关键词 → (厂商名, 余额API地址, 响应解析函数)
# 新增厂商只需在这里加一条即可
BALANCE_PROVIDERS: dict[str, tuple[str, str, callable]] = {
    "api.deepseek.com": ("DeepSeek", "https://api.deepseek.com/user/balance", _parse_deepseek_balance),
    "api.moonshot.cn": ("Kimi", "https://api.moonshot.cn/v1/users/me/balance", _parse_kimi_balance),
}


def detect_provider(base_url: str) -> Optional[tuple[str, str, callable]]:
    """根据 base_url 匹配对应的余额查询厂商"""
    for domain, provider in BALANCE_PROVIDERS.items():
        if domain in base_url:
            return provider
    return None


# 余额缓存：{(base_url, api_key_hash): (result, timestamp)}，缓存 60 秒
_balance_cache: dict[tuple, tuple[dict, float]] = {}
_BALANCE_CACHE_TTL = 60


def _hash_key(api_key: str) -> str:
    return str(hash(api_key))


def check_balance(base_url: str, api_key: str, force: bool = False) -> dict:
    """查询余额，返回 {'success': bool, 'balance': str, 'provider': str, 'error': str}"""
    cache_key = (base_url, _hash_key(api_key))
    if not force:
        cached = _balance_cache.get(cache_key)
        if cached and (time.time() - cached[1]) < _BALANCE_CACHE_TTL:
            return cached[0]
    provider = detect_provider(base_url)
    if not provider:
        return {"success": False, "balance": "", "provider": "未知", "error": "未找到对应的余额查询接口"}

    name, url, parser = provider
    try:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            balance = parser(data)
            result = {"success": True, "balance": balance, "provider": name, "error": ""}
            _balance_cache[cache_key] = (result, time.time())
            return result
    except urllib.error.HTTPError as e:
        return {"success": False, "balance": "", "provider": name, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"success": False, "balance": "", "provider": name, "error": str(e)}


# ─── 对话导出 ──────────────────────────────────────────────────

def _directory_to_project_key(directory: str) -> str:
    """将目录路径转换为 Claude Code 的项目存储键"""
    # 统一使用反斜杠格式
    directory = directory.replace('/', '\\')
    result = []
    for char in directory:
        # 仅保留 ASCII 字母数字、连字符和点号，其余全部替换为 -
        # Claude Code 的实际行为：_ 及非 ASCII 字符（如中文）也会被替换为 -
        if char.isascii() and (char.isalnum() or char in '-.'):
            result.append(char)
        else:
            result.append('-')
    return ''.join(result)


def _get_conversation_files(project_dir: str) -> list[Path]:
    """获取项目目录下的所有对话 JSONL 文件，按时间排序"""
    key = _directory_to_project_key(project_dir)
    project_path = TRANSCRIPTS_DIR / key
    if not project_path.exists():
        return []
    files = sorted(project_path.glob('*.jsonl'), key=lambda p: p.stat().st_mtime)
    return files


def _parse_jsonl(filepath: Path) -> list[dict]:
    """解析单个 JSONL 文件，提取有意义的对话消息（包括系统消息）

    返回空列表时调用方应视为该文件解析失败（无消息或读取错误）。
    异常不在此层静默吞掉，而是向上传播，让调用方统一处理。
    """
    messages = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                msg_type = msg.get('type', '')
                # 包含用户消息、助手回复，以及系统/模式消息
                if msg_type in ('user', 'assistant', 'mode', 'permission-mode'):
                    messages.append(msg)
            except json.JSONDecodeError:
                continue
    return messages


def _render_content_blocks(blocks: list, is_assistant: bool = False, options: dict = None) -> str:
    """将消息内容块渲染为 HTML，options 控制显示哪些内容类型"""
    if options is None:
        options = {}
    parts = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get('type', '')
        # 根据选项过滤内容
        if block_type == 'thinking' and not options.get('thinking', True):
            continue
        if block_type == 'tool_use' and not options.get('tool_use', True):
            continue
        if block_type == 'tool_result' and not options.get('tool_result', True):
            continue
        if block_type == 'text':
            text = block.get('text', '')
            if text:
                # 简单的 Markdown 代码块转换
                text = _html.escape(text)
                # 处理代码块 ```
                text = _format_code_blocks(text)
                # 处理行内代码 `code`
                text = _format_inline_code(text)
                parts.append(f'<div class="msg-text">{text}</div>')
        elif block_type == 'thinking':
            thinking = block.get('thinking', '')
            if thinking:
                thinking_escaped = _html.escape(thinking)
                # 思考内容超过 300 字符则截断，并添加折叠展开交互
                if len(thinking_escaped) > 300:
                    short = thinking_escaped[:300] + '...'
                    think_id = f'think-{id(block)}'
                    parts.append(
                        f'<div class="thinking-block">'
                        f'<div class="thinking-header">'
                        f'<span class="thinking-label">💭 思考过程</span>'
                        f'<span class="thinking-len">({len(thinking)} 字符)</span>'
                        f'</div>'
                        f'<div class="thinking-body thinking-collapsed" id="{think_id}">'
                        f'<div class="thinking-preview">{short}</div>'
                        f'<div class="thinking-full" style="display:none;">{thinking_escaped}</div>'
                        f'</div>'
                        f'<button class="thinking-toggle" onclick="toggleThinking(\'{think_id}\', this)">📋 展开全部</button>'
                        f'</div>'
                    )
                else:
                    parts.append(
                        f'<div class="thinking-block">'
                        f'<div class="thinking-header">'
                        f'<span class="thinking-label">💭 思考过程</span>'
                        f'<span class="thinking-len">({len(thinking)} 字符)</span>'
                        f'</div>'
                        f'<div class="thinking-body">{thinking_escaped}</div>'
                        f'</div>'
                    )
        elif block_type == 'tool_use':
            tool_name = block.get('name', 'unknown')
            tool_input = block.get('input', {})
            # 提取一行关键信息
            brief = _tool_one_liner(tool_name, tool_input)
            parts.append(
                f'<div class="tool-block tool-use">'
                f'<div class="tool-header">🔧 {_html.escape(tool_name)}<span class="tool-brief">{_html.escape(brief)}</span></div>'
                f'</div>'
            )
        elif block_type == 'tool_result':
            content = block.get('content', '')
            if isinstance(content, str):
                result_str = _html.escape(content)
            else:
                result_str = _html.escape(json.dumps(content, ensure_ascii=False, indent=2))
            # 直接截断，不折叠
            if len(result_str) > 150:
                result_str = result_str[:150] + '...'
            if result_str:
                parts.append(
                    f'<div class="tool-block tool-result">'
                    f'<div class="tool-header">📋 工具返回</div>'
                    f'<pre class="tool-body">{result_str}</pre>'
                    f'</div>'
                )
    return '\n'.join(parts)


def _tool_one_liner(tool_name: str, tool_input: dict) -> str:
    """从工具参数中提取一行关键描述"""
    if not tool_input:
        return ''
    # 各工具的关键字段（按优先级）
    key_map = {
        'Bash': ('command', 'description'),
        'Read': ('file_path',),
        'Write': ('file_path',),
        'Edit': ('file_path',),
        'Grep': ('pattern',),
        'Glob': ('pattern',),
        'WebFetch': ('url',),
        'WebSearch': ('query',),
        'Agent': ('description', 'prompt'),
        'Task': ('description', 'subagent_type'),
    }
    fields = key_map.get(tool_name, ())
    for f in fields:
        val = tool_input.get(f, '')
        if val and isinstance(val, str):
            val = val.replace('\n', ' ').strip()
            if len(val) > 100:
                val = val[:100] + '...'
            return f': {val}'
    # fallback: 取第一个字符串值
    for k, v in tool_input.items():
        if isinstance(v, str) and v:
            v = v.replace('\n', ' ').strip()
            if len(v) > 60:
                v = v[:60] + '...'
            return f': {v}'
    return ''


def _format_code_blocks(text: str) -> str:
    """将 ``` 代码块转换为 HTML"""
    import re
    def replace_code_block(m):
        lang = m.group(1) or ''
        code = m.group(2)
        lang_class = f' class="language-{_html.escape(lang)}"' if lang else ''
        return f'<pre{lang_class}><code>{code}</code></pre>'
    return re.sub(r'```(\w*)\n?(.*?)```', replace_code_block, text, flags=re.DOTALL)


def _format_inline_code(text: str) -> str:
    """将 ` 行内代码转换为 HTML"""
    import re
    # 避免在 pre 标签内替换
    parts = re.split(r'(<pre[^>]*>.*?</pre>)', text, flags=re.DOTALL)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r'`([^`]+?)`', r'<code>\1</code>', parts[i])
    return ''.join(parts)


def _format_timestamp(ts: str) -> str:
    """格式化 ISO 时间戳为可读格式"""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ts


def _generate_export_html(all_sessions: list[tuple[Path, list[dict]]], directory: str, options: dict = None) -> str:
    """生成包含所有对话的 HTML 文件，options 控制导出内容"""
    if options is None:
        options = {}
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    dir_name = Path(directory).name or directory

    # Count totals
    total_user = 0
    total_assistant = 0
    for _, msgs in all_sessions:
        for m in msgs:
            if m.get('type') == 'user':
                total_user += 1
            elif m.get('type') == 'assistant':
                total_assistant += 1

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ModelBuddyCC 对话记录 — {_html.escape(dir_name)}</title>
<style>
  :root {{
    --bg: #f8f9fa;
    --card-bg: #ffffff;
    --text: #1a1a2e;
    --text-secondary: #64748b;
    --border: #e2e8f0;
    --user-color: #3b82f6;
    --user-bg: #eff6ff;
    --assistant-color: #10b981;
    --assistant-bg: #f0fdf4;
    --thinking-bg: #fef9e7;
    --thinking-border: #f59e0b;
    --tool-bg: #f8fafc;
    --tool-border: #94a3b8;
    --code-bg: #1e293b;
    --code-text: #e2e8f0;
    --header-bg: #0f172a;
    --header-text: #f1f5f9;
    --session-sep: #6366f1;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #fff;
    color: var(--text);
    line-height: 1.4;
    font-size: 12px;
  }}
  .header {{
    background: var(--header-bg);
    color: var(--header-text);
    padding: 12px 24px;
    text-align: center;
  }}
  .header h1 {{
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .header .meta {{
    font-size: 10px;
    color: #94a3b8;
    display: flex;
    justify-content: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 4px;
  }}
  .header .meta span {{
    background: rgba(255,255,255,0.08);
    padding: 1px 8px;
    border-radius: 16px;
  }}
  .container {{
    max-width: 860px;
    margin: 0 auto;
    padding: 8px 12px 24px;
  }}
  .session-separator {{
    text-align: center;
    margin: 14px 0 8px;
    position: relative;
  }}
  .session-separator::before {{
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    top: 50%;
    height: 1px;
    background: var(--session-sep);
    opacity: 0.15;
  }}
  .session-separator span {{
    display: inline-block;
    background: #fff;
    padding: 0 10px;
    position: relative;
    font-size: 10px;
    font-weight: 600;
    color: var(--session-sep);
  }}
  .message {{
    margin: 6px 0;
    padding: 0;
    border-radius: 6px;
    background: #fff;
    overflow: hidden;
  }}
  .message.user {{
    border: 2px solid var(--user-color);
    border-left: 5px solid var(--user-color);
    background: #eff6ff;
  }}
  .message.assistant {{
    border: 1px solid #d1d5db;
    border-left: 4px solid #9ca3af;
    background: #f9fafb;
  }}
  .message.system-msg {{
    border: 1px solid #e2e8f0;
    border-left: 3px solid #94a3b8;
    background: #f8fafc;
    padding: 4px 10px;
    margin: 3px 0;
  }}
  .message-header {{
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    font-size: 10px;
  }}
  .message.user .message-header {{
    background: #dbeafe;
    border-bottom: 1px solid #93c5fd;
  }}
  .message.assistant .message-header {{
    background: #f3f4f6;
    border-bottom: 1px solid #e5e7eb;
  }}
  .message-header .role {{
    font-weight: 700;
    font-size: 11px;
    padding: 1px 8px;
    border-radius: 10px;
  }}
  .user .message-header .role {{
    background: var(--user-color);
    color: #fff;
  }}
  .assistant .message-header .role {{
    background: var(--assistant-color);
    color: #fff;
  }}
  .system-role {{
    background: #94a3b8 !important;
    color: #fff !important;
    font-size: 9px !important;
  }}
  .system-info {{
    font-size: 10px;
    color: var(--text-secondary);
    font-weight: 500;
  }}
  .message-body {{
    padding: 6px 10px 8px;
  }}
  .message-header .time {{
    color: var(--text-secondary);
    margin-left: auto;
    font-size: 9px;
  }}
  .msg-text {{
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 12px;
    line-height: 1.5;
  }}
  .msg-text p {{ margin: 2px 0; }}
  /* ═══════════════════════════════════════════════
     思考块 — 独特紫色调，与文本/工具块明确区分
     ═══════════════════════════════════════════════ */
  .thinking-block {{
    margin: 8px 0;
    border: 2px dashed #c4b5fd;
    border-left: 5px solid #8b5cf6;
    border-radius: 8px;
    background: linear-gradient(135deg, #faf5ff 0%, #f5f3ff 100%);
    overflow: hidden;
  }}
  .thinking-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: #ede9fe;
    border-bottom: 1px solid #ddd6fe;
  }}
  .thinking-label {{
    font-size: 11px;
    font-weight: 700;
    color: #6d28d9;
  }}
  .thinking-len {{
    font-size: 9px;
    color: #8b5cf6;
    background: #ede9fe;
    padding: 1px 6px;
    border-radius: 8px;
  }}
  .thinking-body {{
    padding: 8px 12px;
    font-size: 11px;
    color: #4c1d95;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.55;
    max-height: 400px;
    overflow-y: auto;
  }}
  .thinking-collapsed .thinking-preview {{
    display: block;
  }}
  .thinking-expanded .thinking-full {{
    display: block;
  }}
  .thinking-preview {{
    font-size: 11px;
    color: #4c1d95;
    line-height: 1.55;
  }}
  .thinking-full {{
    font-size: 11px;
    color: #4c1d95;
    line-height: 1.55;
  }}
  .thinking-toggle {{
    display: block;
    width: 100%;
    padding: 6px 12px;
    font-size: 10px;
    font-weight: 600;
    color: #7c3aed;
    background: #ede9fe;
    border: none;
    border-top: 1px solid #ddd6fe;
    cursor: pointer;
    font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
    transition: all 0.15s ease;
    text-align: center;
  }}
  .thinking-toggle:hover {{
    background: #ddd6fe;
    color: #5b21b6;
  }}
  .thinking-toggle.expanded {{
    color: #6d28d9;
  }}
  /* 短思考：内联样式 */
  .thinking-inline {{
    margin: 3px 0;
    padding: 4px 10px;
    border: 2px dotted #c4b5fd;
    border-left: 4px solid #a78bfa;
    border-radius: 6px;
    background: #faf5ff;
    font-size: 11px;
    line-height: 1.5;
    color: #5b21b6;
  }}
  .thinking-label-inline {{
    font-size: 12px;
  }}
  .thinking-text-inline {{
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .tool-block {{
    margin: 3px 0;
    border: 1px solid #334155;
    border-radius: 4px;
    background: #1e293b;
    overflow: hidden;
  }}
  .tool-header {{
    padding: 2px 8px;
    font-size: 10px;
    font-weight: 600;
    color: #e2e8f0;
    background: #334155;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .tool-brief {{
    font-weight: 400;
    color: #94a3b8;
    margin-left: 3px;
    font-size: 9px;
  }}
  .tool-body {{
    padding: 3px 8px;
    font-size: 9px;
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 100px;
    overflow-y: auto;
    color: #cbd5e1;
    background: #0f172a;
    line-height: 1.3;
  }}
  pre {{
    background: var(--code-bg);
    color: var(--code-text);
    padding: 6px 10px;
    border-radius: 4px;
    overflow-x: auto;
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    font-size: 10px;
    line-height: 1.4;
    margin: 4px 0;
  }}
  code {{
    background: #f1f5f9;
    color: #e11d48;
    padding: 1px 3px;
    border-radius: 2px;
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    font-size: 0.9em;
  }}
  pre code {{
    background: none;
    color: inherit;
    padding: 0;
    border-radius: 0;
    font-size: inherit;
  }}
  .footer {{
    text-align: center;
    padding: 12px 12px;
    color: var(--text-secondary);
    font-size: 9px;
  }}
  .empty-state {{
    text-align: center;
    padding: 80px 20px;
    color: var(--text-secondary);
  }}
  .empty-state .icon {{ font-size: 48px; margin-bottom: 16px; }}
  .empty-state p {{ font-size: 14px; }}

  /* 打印样式 */
  @media print {{
    body {{
      background: #fff;
      font-size: 10px;
      line-height: 1.3;
    }}
    .header {{
      background: #0f172a !important;
      padding: 8px 20px !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .header h1 {{ font-size: 14px !important; }}
    .container {{
      max-width: 100%;
      padding: 4px 0 12px;
    }}
    .message {{
      break-inside: avoid;
      box-shadow: none;
      margin: 4px 0;
      border: 1px solid #cbd5e1;
      border-left-width: 4px;
    }}
    .message.user {{
      border: 2px solid #3b82f6 !important;
      border-left: 5px solid #3b82f6 !important;
      background: #eff6ff !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .message.assistant {{
      border: 1px solid #d1d5db !important;
      border-left: 4px solid #9ca3af !important;
      background: #f9fafb !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .message.user .message-header {{
      background: #dbeafe !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .message.assistant .message-header {{
      background: #f3f4f6 !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .message.system-msg {{
      background: #f8fafc !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .thinking-block {{
      background: #faf5ff !important;
      border: 2px dashed #c4b5fd !important;
      border-left: 5px solid #8b5cf6 !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .thinking-header {{
      background: #ede9fe !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .thinking-body {{
      max-height: none;
      color: #4c1d95 !important;
    }}
    .thinking-toggle {{
      display: none !important;
    }}
    .thinking-collapsed .thinking-preview {{
      display: block !important;
    }}
    .thinking-collapsed .thinking-full {{
      display: none !important;
    }}
    .tool-block {{
      background: #1e293b !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .tool-header {{
      background: #334155 !important;
      color: #e2e8f0 !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .tool-body {{
      max-height: none;
      color: #cbd5e1 !important;
      background: #0f172a !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    pre {{
      background: #1e293b !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    @page {{
      margin: 8mm;
      size: A4;
    }}
  }}
</style>
</head>
<body>
<div class="header">
  <h1>📄 ModelBuddyCC 对话记录</h1>
  <div style="font-size:15px;margin-top:4px;">{_html.escape(directory)}</div>
  <div class="meta">
    <span>📁 {len(all_sessions)} 个会话</span>
    <span>💬 {total_user + total_assistant} 条消息</span>
    <span>👤 用户消息 {total_user}</span>
    <span>🤖 助手回复 {total_assistant}</span>
    <span>📅 导出时间 {now}</span>
  </div>
</div>
<div class="container">
'''

    if not all_sessions:
        html += '''
<div class="empty-state">
  <div class="icon">📭</div>
  <p>该目录下暂无对话记录</p>
</div>
'''

    for session_idx, (filepath, messages) in enumerate(all_sessions):
        if not messages:
            continue

        # Session separator
        session_time = ''
        for m in messages:
            ts = m.get('timestamp', '')
            if ts:
                session_time = _format_timestamp(ts)
                break

        session_name = filepath.stem[:8] + '...'
        html += f'''
<div class="session-separator">
  <span>会话 #{session_idx + 1} · {session_name} · {session_time}</span>
</div>
'''

        for msg in messages:
            msg_type = msg.get('type', '')
            timestamp = _format_timestamp(msg.get('timestamp', ''))

            # 系统消息（模式切换等）
            if msg_type in ('mode', 'permission-mode'):
                if not options.get('system', True):
                    continue
                mode_name = msg.get('mode', msg.get('permissionMode', ''))
                mode_label = '模式' if msg_type == 'mode' else '权限'
                html += f'''
<div class="message system-msg">
  <div class="message-header">
    <span class="role system-role">⚙ 系统</span>
    <span class="system-info">{mode_label}：{_html.escape(mode_name)}</span>
    <span class="time">{timestamp}</span>
  </div>
</div>
'''
                continue

            # 用户/助手消息过滤
            if msg_type == 'user' and not options.get('user', True):
                continue
            if msg_type == 'assistant' and not options.get('assistant', True):
                continue

            role_class = msg_type  # 'user' or 'assistant'

            content = msg.get('message', {}).get('content', '')
            if isinstance(content, str):
                # User text messages
                content_html = f'<div class="msg-text">{_html.escape(content)}</div>'
            elif isinstance(content, list):
                content_html = _render_content_blocks(content, is_assistant=(msg_type == 'assistant'), options=options)
            else:
                content_html = ''

            if not content_html:
                continue

            role_label = '👤 用户' if msg_type == 'user' else '🤖 Claude'
            model_info = ''
            if msg_type == 'assistant':
                model = msg.get('message', {}).get('model', '')
                if model:
                    model_info = f' · <em>{_html.escape(model)}</em>'

            html += f'''
<div class="message {role_class}">
  <div class="message-header">
    <span class="role">{role_label}</span>
    {model_info}
    <span class="time">{timestamp}</span>
  </div>
  <div class="message-body">
  {content_html}
  </div>
</div>
'''

    html += '''
<div class="footer">
  <p>由 ModelBuddyCC 生成 · 可在浏览器中另存为 PDF</p>
</div>
</div>
<script>
function toggleThinking(id, btn) {
  var el = document.getElementById(id);
  if (!el) return;
  var preview = el.querySelector('.thinking-preview');
  var full = el.querySelector('.thinking-full');
  var isCollapsed = el.classList.contains('thinking-collapsed');
  if (isCollapsed) {
    el.classList.remove('thinking-collapsed');
    el.classList.add('thinking-expanded');
    if (preview) preview.style.display = 'none';
    if (full) full.style.display = 'block';
    btn.textContent = '📋 收起';
    btn.classList.add('expanded');
  } else {
    el.classList.remove('thinking-expanded');
    el.classList.add('thinking-collapsed');
    if (preview) preview.style.display = 'block';
    if (full) full.style.display = 'none';
    btn.textContent = '📋 展开全部';
    btn.classList.remove('expanded');
  }
}
</script>
</body>
</html>
'''
    return html


# ─── 数据模型 ───────────────────────────────────────────────
@dataclass
class ModelProfile:
    name: str
    base_url: str
    api_key: str
    model: str
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelProfile":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class LaunchRecord:
    directory: str
    label: str = ""
    opened_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LaunchRecord":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


# ─── 配置管理器 ──────────────────────────────────────────────
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
            # 先读取文件内容，再做备份（避免两次读文件）
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

            # 备份
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(str(CLAUDE_SETTINGS), str(BACKUP_DIR / f"settings.json.{ts}.bak"))

            # 只保留最新 5 个 settings 备份
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


# ─── 余额仪表盘窗口 ────────────────────────────────────────────
class BalanceDashboard(ctk.CTkToplevel):
    def __init__(self, parent, profiles: list[ModelProfile]):
        super().__init__(parent)

        self.title("账户余额仪表盘")
        self.geometry("560x480")
        self.minsize(420, 320)
        self.transient(parent)

        self.profiles = profiles
        self.result_widgets: list = []

        self._build()

        # 居中
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # 自动开始查询
        self.after(200, self._fetch_all)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.configure(fg_color=COLORS["bg_dark"])

        # 顶部栏
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="账户余额仪表盘",
            font=(FONT_FAMILY, 16, "bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.btn_refresh = ctk.CTkButton(
            header,
            text="刷新",
            command=self._fetch_all,
            width=80,
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=6,
        )
        self.btn_refresh.grid(row=0, column=1, sticky="e", padx=(8, 0))

        # 可滚动的卡片区域
        self.scroll = ctk.CTkScrollableFrame(self, corner_radius=8,
                                             fg_color="transparent")
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self.scroll.grid_columnconfigure(0, weight=1)

        self._build_cards()

    def _build_cards(self):
        for profile in self.profiles:
            provider = detect_provider(profile.base_url)
            provider_name = provider[0] if provider else "未知厂商"

            card = ctk.CTkFrame(self.scroll, corner_radius=10,
                                fg_color=COLORS["bg_card"])
            card.pack(fill="x", padx=2, pady=4)
            card.grid_columnconfigure(1, weight=1)

            # 配置名 + 厂商标签
            ctk.CTkLabel(
                card,
                text=profile.name,
                font=(FONT_FAMILY, 14, "bold"),
                text_color=COLORS["text_primary"],
                anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=(16, 6), pady=(12, 0))

            tag_color = COLORS["accent"] if provider else COLORS["text_muted"]
            ctk.CTkLabel(
                card,
                text=provider_name,
                font=(FONT_FAMILY, 11),
                text_color=COLORS["text_primary"],
                fg_color=tag_color,
                corner_radius=4,
                padx=8,
            ).grid(row=0, column=1, sticky="w", padx=(4, 0), pady=(12, 0))

            # 模型名
            ctk.CTkLabel(
                card,
                text=profile.model,
                font=(FONT_FAMILY, 11),
                text_color=COLORS["text_muted"],
                anchor="w",
            ).grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 0))

            # 余额显示（初始加载中）
            balance_lbl = ctk.CTkLabel(
                card,
                text="查询中...",
                font=(FONT_FAMILY, 20, "bold"),
                text_color=COLORS["warning"],
                anchor="e",
            )
            balance_lbl.grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 16), pady=(12, 12))

            self.result_widgets.append((balance_lbl, profile))

    def _fetch_all(self):
        self.btn_refresh.configure(text="查询中...", state="disabled")
        for lbl, _ in self.result_widgets:
            lbl.configure(text="查询中...", text_color=COLORS["text_muted"])

        def fetch():
            results = [None] * len(self.result_widgets)
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(check_balance, profile.base_url, profile.api_key, True): i
                    for i, (_, profile) in enumerate(self.result_widgets)
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    results[idx] = future.result()
            self.after(0, lambda: self._update_results(results))

        threading.Thread(target=fetch, daemon=True).start()

    def _update_results(self, results: list[dict]):
        self.btn_refresh.configure(text="刷新", state="normal")
        for (lbl, _), result in zip(self.result_widgets, results):
            if result["success"]:
                lbl.configure(text=result["balance"], text_color=COLORS["success"])
            else:
                lbl.configure(text=result["error"], text_color=COLORS["danger"])


# ─── 主窗口 ──────────────────────────────────────────────────
class ModelSwitcherApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ModelBuddyCC")
        self.geometry("920x680")
        self.minsize(780, 560)
        self.configure(fg_color=COLORS["bg_dark"])

        # 初始化数据（延迟加载）
        self.profiles: list[ModelProfile] = []
        self.current_env: dict = {}
        self.selected_index: Optional[int] = None
        self._list_frames: dict[int, ctk.CTkFrame] = {}  # 列表项帧缓存

        # Claude 启动器状态
        self.launch_history: list[LaunchRecord] = []
        self._auto_launch = ctk.BooleanVar(value=False)
        self.current_mode: str = "default"  # 当前执行模式

        # 导出状态（防止并发导出）
        self._export_busy = False

        # 图标 Unicode（windows 兼容）
        self.icons = {
            "add": "＋",
            "edit": "✎",
            "delete": "✕",
            "apply": "▶",
            "backup": "↺",
        }

        self._build_ui()
        # 延迟加载数据，不阻塞窗口首屏渲染
        self.after(50, self._load_data)

        # 启动系统主题检测
        self._last_appearance = _appearance_mode
        self._theme_check_loop()

        # 窗口关闭事件
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # 状态栏
        self.grid_rowconfigure(1, weight=1)  # tabview

        # ── 顶部状态栏 ──
        self.status_frame = ctk.CTkFrame(self, height=60, corner_radius=0,
                                         fg_color=COLORS["bg_card"])
        self.status_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.status_frame.grid_columnconfigure(1, weight=1)
        self.status_frame.grid_propagate(False)

        status_left = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        status_left.pack(side="left", padx=20, pady=12)

        ctk.CTkLabel(
            status_left,
            text="⚡",
            font=(FONT_FAMILY, 18),
        ).pack(side="left", padx=(0, 8))

        self.status_label = ctk.CTkLabel(
            status_left,
            text="加载中...",
            font=(FONT_FAMILY, 14, "bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        )
        self.status_label.pack(side="left")

        # ── 执行模式选择器 ──
        self.mode_frame = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.mode_frame.pack(side="right", padx=(0, 8), pady=8)

        self.mode_label = ctk.CTkLabel(
            self.mode_frame,
            text="执行模式",
            font=(FONT_FAMILY, 10, "bold"),
            text_color=COLORS["text_muted"],
        )
        self.mode_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=(0, 0), pady=(0, 1))

        self.mode_combo = ctk.CTkComboBox(
            self.mode_frame,
            values=[EXECUTION_MODES[k]["label"] for k in EXECUTION_MODE_KEYS],
            font=(FONT_FAMILY, 12),
            width=210,
            height=30,
            fg_color=COLORS["bg_input"],
            border_color=COLORS["border"],
            button_color=COLORS["bg_hover"],
            button_hover_color=COLORS["accent"],
            corner_radius=6,
            dropdown_font=(FONT_FAMILY, 12),
            command=self._on_mode_changed,
        )
        self.mode_combo.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self._mode_label_to_key = {EXECUTION_MODES[k]["label"]: k for k in EXECUTION_MODE_KEYS}

        # 应用按钮
        self.btn_apply_mode = ctk.CTkButton(
            self.mode_frame,
            text="应用",
            command=self._on_apply_mode,
            width=50,
            height=30,
            font=(FONT_FAMILY, 11, "bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=6,
        )
        self.btn_apply_mode.grid(row=1, column=1, sticky="e")

        # 模式说明小字
        self.mode_desc_label = ctk.CTkLabel(
            self.mode_frame,
            text="",
            font=(FONT_FAMILY, 8),
            text_color=COLORS["text_muted"],
        )
        self.mode_desc_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(1, 0))

        self.status_badge = ctk.CTkLabel(
            self.status_frame,
            text="",
            font=(FONT_FAMILY, 11),
            text_color=COLORS["accent_light"],
            fg_color=COLORS["bg_hover"],
            corner_radius=6,
            padx=10,
        )
        self.status_badge.pack(side="right", padx=20, pady=14)

        # ── Tabview ──
        self.tabview = ctk.CTkTabview(self, corner_radius=10,
                                      fg_color=COLORS["bg_dark"])
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 12))

        self.tab_model = self.tabview.add("模型配置")
        self.tab_launcher = self.tabview.add("Claude 启动器")

        # ── Tab 1：模型配置 ──
        self.tab_model.grid_columnconfigure(0, weight=1)
        self.tab_model.grid_rowconfigure(0, weight=1)  # 主区域
        self.tab_model.grid_rowconfigure(1, weight=0)  # 底部按钮

        # 主区域：左侧列表 + 右侧详情
        self.main_frame = ctk.CTkFrame(self.tab_model, fg_color="transparent")
        self.main_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.main_frame.grid_columnconfigure(0, weight=0)
        self.main_frame.grid_columnconfigure(1, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)

        # 左侧：配置列表
        self.list_frame = ctk.CTkFrame(self.main_frame, width=320, corner_radius=10,
                                       fg_color=COLORS["bg_card"])
        self.list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.list_frame.grid_rowconfigure(1, weight=1)

        self.list_header = ctk.CTkLabel(
            self.list_frame,
            text="已保存的配置",
            font=(FONT_FAMILY, 13, "bold"),
            text_color=COLORS["text_secondary"],
            anchor="w",
            height=36,
        )
        self.list_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 0))

        self.listbox_frame = ctk.CTkScrollableFrame(
            self.list_frame, corner_radius=6,
            fg_color="transparent",
        )
        self.listbox_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self.listbox_frame.grid_columnconfigure(0, weight=1)

        # 右侧：详情面板
        self.detail_frame = ctk.CTkFrame(self.main_frame, corner_radius=10,
                                         fg_color=COLORS["bg_card"])
        self.detail_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.detail_frame.grid_columnconfigure(1, weight=1)

        # 详情标题（空状态居中提示）
        self.detail_placeholder = ctk.CTkLabel(
            self.detail_frame,
            text="← 从左侧选择一个配置\n\n或点击下方 [+ 新建] 添加",
            font=(FONT_FAMILY, 13),
            text_color=COLORS["text_muted"],
            justify="center",
        )
        self.detail_placeholder.place(relx=0.5, rely=0.45, anchor="center")

        # 详情字段（先创建，默认隐藏）
        self.detail_widgets = {}
        self._build_detail_widgets()

        # 底部操作栏
        self.action_frame = ctk.CTkFrame(self.tab_model, fg_color=COLORS["bg_card"],
                                         corner_radius=0)
        self.action_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.action_frame.grid_columnconfigure(0, weight=1)

        btn_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        btn_frame.pack(fill="both", expand=True, padx=16, pady=10)

        self.btn_add = ctk.CTkButton(
            btn_frame,
            text=f"{self.icons['add']} 新建",
            command=self._on_add,
            width=95,
            height=34,
            font=(FONT_FAMILY, 12, "bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=6,
        )
        self.btn_add.pack(side="left", padx=(0, 6))

        self.btn_edit = ctk.CTkButton(
            btn_frame,
            text=f"{self.icons['edit']} 编辑",
            command=self._on_edit,
            width=80,
            height=34,
            font=(FONT_FAMILY, 12),
            state="disabled",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            text_color_disabled=COLORS["text_muted"],
            corner_radius=6,
        )
        self.btn_edit.pack(side="left", padx=4)

        self.btn_delete = ctk.CTkButton(
            btn_frame,
            text=f"{self.icons['delete']} 删除",
            command=self._on_delete,
            width=80,
            height=34,
            font=(FONT_FAMILY, 12),
            state="disabled",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["danger"],
            text_color=COLORS["text_primary"],
            text_color_disabled=COLORS["text_muted"],
            corner_radius=6,
        )
        self.btn_delete.pack(side="left", padx=4)

        self.btn_backup = ctk.CTkButton(
            btn_frame,
            text=f"{self.icons['backup']} 打开备份",
            command=self._open_backup,
            width=95,
            height=34,
            font=(FONT_FAMILY, 11),
            fg_color="transparent",
            text_color=COLORS["text_muted"],
            hover_color=COLORS["bg_hover"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=6,
        )
        self.btn_backup.pack(side="left", padx=4)

        self.btn_dashboard = ctk.CTkButton(
            btn_frame,
            text="📊 仪表盘",
            command=self._on_dashboard,
            width=90,
            height=34,
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["warning"],
            hover_color=COLORS["warning_hover"],
            corner_radius=6,
        )
        self.btn_dashboard.pack(side="left", padx=4)

        # 右侧：应用按钮
        self.btn_apply = ctk.CTkButton(
            btn_frame,
            text=f"{self.icons['apply']}  应用配置",
            command=self._on_apply,
            height=38,
            font=(FONT_FAMILY, 13, "bold"),
            fg_color=COLORS["success"],
            hover_color=COLORS["success_hover"],
            state="disabled",
            corner_radius=6,
        )
        self.btn_apply.pack(side="right", padx=(6, 0))

        self.btn_open_config = ctk.CTkButton(
            btn_frame,
            text="打开 .claude.json",
            command=self._open_config,
            width=120,
            height=34,
            font=(FONT_FAMILY, 11),
            fg_color="transparent",
            text_color=COLORS["text_muted"],
            hover_color=COLORS["bg_hover"],
            corner_radius=6,
        )
        self.btn_open_config.pack(side="right", padx=4)

        # ── Tab 2：Claude 启动器 ──
        self._build_launcher_tab()

    def _build_detail_widgets(self):
        """构建详情字段（初始隐藏）"""
        # 配置标题区
        self.detail_title = ctk.CTkLabel(
            self.detail_frame,
            text="",
            font=(FONT_FAMILY, 18, "bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        )
        self.detail_title.grid(row=0, column=0, columnspan=2, sticky="w",
                               padx=20, pady=(18, 4))
        self.detail_title._show = False

        self.detail_model_badge = ctk.CTkLabel(
            self.detail_frame,
            text="",
            font=(FONT_FAMILY, 11),
            fg_color=COLORS["bg_hover"],
            corner_radius=4,
            padx=8,
        )
        self.detail_model_badge.grid(row=1, column=0, columnspan=2, sticky="w",
                                     padx=20, pady=(0, 14))
        self.detail_model_badge._show = False
        self.detail_widgets["_title"] = (self.detail_title, self.detail_model_badge)

        # 分隔线
        sep1 = ctk.CTkFrame(self.detail_frame, height=1, fg_color=COLORS["border"])
        sep1.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 12))
        sep1._show = False
        self.detail_widgets["_sep1"] = (sep1,)

        row = 3
        labels = [
            ("API 地址", "base_url"),
            ("API 密钥", "api_key"),
            ("备注", "notes"),
        ]

        for text, key in labels:
            lbl = ctk.CTkLabel(
                self.detail_frame,
                text=text,
                font=(FONT_FAMILY, 11, "bold"),
                text_color=COLORS["text_muted"],
                anchor="w",
            )
            lbl.grid(row=row, column=0, columnspan=2, sticky="w", padx=(20, 16), pady=(12, 2))
            lbl._show = False

            val = ctk.CTkLabel(
                self.detail_frame,
                text="",
                font=(FONT_FAMILY, 13),
                text_color=COLORS["text_primary"],
                anchor="w",
                wraplength=380,
                justify="left",
            )
            val.grid(row=row + 1, column=0, columnspan=2, sticky="ew", padx=(20, 16), pady=(0, 4))
            val._show = False

            self.detail_widgets[key] = (lbl, val)
            row += 2

        # 分隔线
        sep2 = ctk.CTkFrame(self.detail_frame, height=1, fg_color=COLORS["border"])
        sep2.grid(row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=(8, 12))
        sep2._show = False
        self.detail_widgets["_sep2"] = (sep2,)
        row += 1

        for text, key in [
            ("创建时间", "created_at"),
            ("最后更新", "updated_at"),
        ]:
            lbl = ctk.CTkLabel(
                self.detail_frame,
                text=text,
                font=(FONT_FAMILY, 11),
                text_color=COLORS["text_muted"],
                anchor="w",
            )
            lbl.grid(row=row, column=0, sticky="w", padx=(20, 8))
            lbl._show = False

            val = ctk.CTkLabel(
                self.detail_frame,
                text="",
                font=(FONT_FAMILY, 11),
                text_color=COLORS["text_secondary"],
                anchor="w",
            )
            val.grid(row=row, column=1, sticky="w", padx=(0, 16))
            val._show = False

            self.detail_widgets[key] = (lbl, val)
            row += 1

    # ── Claude 启动器 Tab ─────────────────────────────────────

    def _build_launcher_tab(self):
        self.tab_launcher.grid_columnconfigure(0, weight=1)
        self.tab_launcher.grid_rowconfigure(0, weight=0)
        self.tab_launcher.grid_rowconfigure(1, weight=0)
        self.tab_launcher.grid_rowconfigure(2, weight=1)

        # ── 目录选择区 ──
        self.dir_frame = ctk.CTkFrame(self.tab_launcher, corner_radius=10,
                                 fg_color=COLORS["bg_card"])
        self.dir_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        self.dir_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.dir_frame, text="项目目录", font=(FONT_FAMILY, 12, "bold"),
            text_color=COLORS["text_muted"], anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(16, 8), pady=(14, 6))

        self.launcher_dir_entry = ctk.CTkEntry(
            self.dir_frame, font=(FONT_FAMILY, 13), height=38,
            placeholder_text="选择或输入项目目录路径...",
            fg_color=COLORS["bg_input"],
            border_color=COLORS["border"],
            corner_radius=6,
        )
        self.launcher_dir_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(14, 6))

        ctk.CTkButton(
            self.dir_frame, text="浏览...", command=self._on_browse_directory,
            width=70, height=38, font=(FONT_FAMILY, 12),
            fg_color=COLORS["bg_hover"], hover_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            corner_radius=6,
        ).grid(row=0, column=2, sticky="e", padx=(0, 16), pady=(14, 6))

        ctk.CTkLabel(
            self.dir_frame, text="标签备注", font=(FONT_FAMILY, 12, "bold"),
            text_color=COLORS["text_muted"], anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=(16, 8), pady=(0, 14))

        self.launcher_label_entry = ctk.CTkEntry(
            self.dir_frame, font=(FONT_FAMILY, 13), height=38,
            placeholder_text="可选，如项目名称...",
            fg_color=COLORS["bg_input"],
            border_color=COLORS["border"],
            corner_radius=6,
        )
        self.launcher_label_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(0, 14))

        # ── 启动按钮 + 自动开关 ──
        self.ctrl_frame = ctk.CTkFrame(self.tab_launcher, corner_radius=10,
                                  fg_color=COLORS["bg_card"])
        self.ctrl_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.ctrl_frame.grid_columnconfigure(2, weight=1)

        self.btn_launch = ctk.CTkButton(
            self.ctrl_frame,
            text="🚀  在此目录打开 Claude",
            command=self._on_launch,
            height=42,
            font=(FONT_FAMILY, 13, "bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=8,
        )
        self.btn_launch.grid(row=0, column=0, sticky="w", padx=(16, 12), pady=14)

        self.btn_export = ctk.CTkButton(
            self.ctrl_frame,
            text="📄 导出对话",
            command=self._on_export_conversations,
            height=42,
            font=(FONT_FAMILY, 13, "bold"),
            fg_color=COLORS["warning"],
            hover_color=COLORS["warning_hover"],
            corner_radius=8,
        )
        self.btn_export.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=14)

        self.auto_launch_check = ctk.CTkCheckBox(
            self.ctrl_frame,
            text="切换配置后自动在此目录打开 Claude",
            variable=self._auto_launch,
            font=(FONT_FAMILY, 12),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            border_color=COLORS["border"],
            checkmark_color=COLORS["text_primary"],
        )
        self.auto_launch_check.grid(row=0, column=2, sticky="e", padx=(0, 16), pady=14)

        # ── 历史记录区 ──
        hist_header = ctk.CTkFrame(self.tab_launcher, fg_color="transparent")
        hist_header.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 2))
        hist_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hist_header,
            text="打开历史",
            font=(FONT_FAMILY, 13, "bold"),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.btn_clear_history = ctk.CTkButton(
            hist_header,
            text="清除全部",
            command=self._on_clear_history,
            width=70,
            height=26,
            font=(FONT_FAMILY, 11),
            fg_color="transparent",
            text_color=COLORS["danger"],
            hover_color=COLORS["bg_hover"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=4,
        )
        self.btn_clear_history.grid(row=0, column=1, sticky="e")
        self.btn_clear_history.grid_remove()

        self.launcher_history_frame = ctk.CTkScrollableFrame(
            self.tab_launcher, corner_radius=8,
            fg_color="transparent",
        )
        self.launcher_history_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=6)
        self.launcher_history_frame.grid_columnconfigure(0, weight=1)

        self.tab_launcher.grid_rowconfigure(3, weight=1)

    def _on_browse_directory(self):
        path = filedialog.askdirectory(title="选择项目目录")
        if path:
            self.launcher_dir_entry.delete(0, "end")
            self.launcher_dir_entry.insert(0, path)

    def _on_launch(self):
        directory = self.launcher_dir_entry.get().strip()
        if not directory:
            messagebox.showwarning("提示", "请输入或选择一个目录。")
            return
        if not os.path.isdir(directory):
            messagebox.showwarning("提示", f"目录不存在：\n{directory}")
            return
        self._launch_claude(directory)

    def _launch_claude(self, directory: str, label: str = ""):
        if not label:
            label = self.launcher_label_entry.get().strip()
        self._add_launch_record(directory, label)

        # 确保最新模式已写入 settings.json（以防万一）
        ConfigManager.save_default_mode(self.current_mode)

        # 构建带执行模式参数的 claude 命令
        mode_flag = f"--permission-mode {self.current_mode}" if self.current_mode != "default" else ""

        # 多条启动命令，依次尝试
        launch_cmds = [
            ['wt', '-d', directory, 'cmd', '/k', f'claude {mode_flag}'.strip()],
            ['start', 'cmd', '/k', f'cd /d "{directory}" && claude {mode_flag}'.strip()],
        ]

        for cmd in launch_cmds:
            try:
                shell = cmd[0] == 'start'
                subprocess.Popen(cmd[1:] if shell else cmd, shell=shell,
                                 creationflags=subprocess.CREATE_NO_WINDOW if not shell else 0)
                return
            except (FileNotFoundError, Exception):
                continue

        # 所有方式都失败，提示用户
        messagebox.showwarning(
            "启动失败",
            f"无法启动 Claude。\n\n"
            f"目录：{directory}\n\n"
            f"请确认已安装 claude 命令。\n"
            f"你也可以手动在该目录打开终端并运行 claude。",
        )

    def _add_launch_record(self, directory: str, label: str = ""):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 移除同目录的旧记录
        self.launch_history = [r for r in self.launch_history if r.directory != directory]
        self.launch_history.insert(0, LaunchRecord(
            directory=directory,
            label=label,
            opened_at=now,
        ))
        # 最多 50 条
        if len(self.launch_history) > 50:
            self.launch_history = self.launch_history[:50]
        ConfigManager.save_launch_history(self.launch_history)
        self._refresh_launch_history()

    def _on_clear_history(self):
        if not self.launch_history:
            return
        ok = messagebox.askyesno("确认清除", "确定要清除全部打开历史吗？", icon="warning")
        if ok:
            self.launch_history.clear()
            ConfigManager.save_launch_history(self.launch_history)
            self._refresh_launch_history()

    def _refresh_launch_history(self):
        for w in self.launcher_history_frame.winfo_children():
            w.destroy()

        if not self.launch_history:
            empty = ctk.CTkLabel(
                self.launcher_history_frame,
                text="暂无打开记录\n在上方选择目录后点击启动按钮",
                font=(FONT_FAMILY, 12),
                text_color=COLORS["text_muted"],
                justify="center",
            )
            empty.pack(expand=True, fill="both", pady=40)
            self.btn_clear_history.grid_remove()
            return

        self.btn_clear_history.grid()

        for record in self.launch_history:
            self._create_history_item(record)

    def _create_history_item(self, record: LaunchRecord):
        card = ctk.CTkFrame(self.launcher_history_frame, corner_radius=8,
                            fg_color=COLORS["bg_card"])
        card.pack(fill="x", padx=2, pady=3)
        card.grid_columnconfigure(1, weight=1)

        # 目录路径
        dir_lbl = ctk.CTkLabel(
            card,
            text=record.directory,
            font=(FONT_FAMILY, 12, "bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        )
        dir_lbl.grid(row=0, column=0, columnspan=2, sticky="w", padx=(14, 8), pady=(10, 0))

        # 标签 + 时间
        info_parts = []
        if record.label:
            info_parts.append(f"📌 {record.label}")
        info_parts.append(f"🕐 {record.opened_at}")
        info_text = "    ".join(info_parts)

        ctk.CTkLabel(
            card,
            text=info_text,
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=(14, 8), pady=(4, 10))

        # 操作按钮
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 10), pady=8)

        ctk.CTkButton(
            btn_frame,
            text="▶",
            command=lambda d=record.directory, l=record.label: self._launch_claude(d, l),
            width=32, height=28,
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["success"],
            hover_color=COLORS["success_hover"],
            corner_radius=6,
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            btn_frame,
            text="📄",
            command=lambda d=record.directory: self._on_export_conversations(d),
            width=32, height=28,
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["warning"],
            hover_color=COLORS["warning_hover"],
            corner_radius=6,
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            btn_frame,
            text="📂",
            command=lambda d=record.directory: os.startfile(d) if os.path.isdir(d) else None,
            width=32, height=28,
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent"],
            text_color=COLORS["text_primary"],
            corner_radius=6,
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            btn_frame,
            text="✕",
            command=lambda r=record: self._on_delete_history(r),
            width=32, height=28,
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["danger"],
            text_color=COLORS["text_primary"],
            corner_radius=6,
        ).pack(side="left", padx=3)

    def _on_delete_history(self, record: LaunchRecord):
        self.launch_history = [r for r in self.launch_history if r.directory != record.directory or r.opened_at != record.opened_at]
        ConfigManager.save_launch_history(self.launch_history)
        self._refresh_launch_history()

    # ── 对话导出 ─────────────────────────────────────────────

    def _on_export_conversations(self, directory: str = ""):
        """导出指定目录下的 Claude 对话为 HTML"""
        # ── 防止重入 ─────────────────────────────────────────
        if getattr(self, '_export_busy', False):
            messagebox.showwarning("提示", "正在导出中，请等待当前导出完成。")
            return
        self._export_busy = True

        try:
            self._do_export_conversations(directory)
        finally:
            self._export_busy = False

    def _do_export_conversations(self, directory: str):
        if not directory:
            directory = self.launcher_dir_entry.get().strip()
        if not directory:
            messagebox.showwarning("提示", "请先输入或选择一个项目目录。")
            return
        if not os.path.isdir(directory):
            messagebox.showwarning("提示", f"目录不存在：\n{directory}")
            return

        # ── 查找对话文件 ────────────────────────────────────
        files = _get_conversation_files(directory)
        if not files:
            # 也尝试在项目本地 .claude 中查找
            local_claude = Path(directory) / '.claude'
            if local_claude.exists():
                local_files = sorted(local_claude.glob('*.jsonl'), key=lambda p: p.stat().st_mtime)
                files = local_files

        if not files:
            messagebox.showinfo(
                "无对话记录",
                f"在该目录下未找到 Claude Code 对话记录。\n\n目录：{directory}\n\n"
                f"请确认曾在该目录中使用过 Claude Code。"
            )
            return

        # ── 在主线程预解析所有文件（消除竞态条件）───────────
        # 先解析再弹对话框，确保文件内容在用户操作前已确定
        all_sessions = []
        skipped_files = []
        total_msgs = 0
        for fp in files:
            try:
                msgs = _parse_jsonl(fp)
                if msgs:
                    all_sessions.append((fp, msgs))
                    total_msgs += len(msgs)
                else:
                    skipped_files.append(f"{fp.name}（无有效消息）")
            except Exception as parse_err:
                skipped_files.append(f"{fp.name}（读取错误：{parse_err}）")

        # ── 按对话实际发生时间排序（而非文件修改时间）───────
        # st_mtime 可能因为后续操作被刷新，导致顺序错乱
        def _session_first_ts(session_tuple):
            _fp, msgs = session_tuple
            for m in msgs:
                ts = m.get('timestamp', '')
                if ts:
                    return ts
            return '9999'  # 无时间戳的放到最后

        all_sessions.sort(key=_session_first_ts)

        if not all_sessions:
            detail = ""
            if skipped_files:
                detail = "\n\n跳过详情：\n" + "\n".join(skipped_files)
            messagebox.showinfo("无有效对话", f"未找到可导出的对话内容。{detail}")
            return

        # ── 弹出选项对话框 ──────────────────────────────────
        opt_dialog = ExportOptionsDialog(self)
        if not opt_dialog.result:
            return  # 用户取消
        options = opt_dialog.result

        # ── 选择保存路径 ─────────────────────────────────────
        dir_name = Path(directory).name or "conversations"
        save_path = filedialog.asksaveasfilename(
            title="导出对话 HTML",
            initialfile=f"claude-conversations-{dir_name}.html",
            defaultextension=".html",
            filetypes=[("HTML 文件", "*.html"), ("所有文件", "*.*")],
        )
        if not save_path:
            return

        # ── 构建文件统计信息 ─────────────────────────────────
        file_details = []
        for fp, msgs in all_sessions:
            user_n = sum(1 for m in msgs if m.get('type') == 'user')
            asst_n = sum(1 for m in msgs if m.get('type') == 'assistant')
            file_details.append(f"  📄 {fp.name[:20]}... → 👤{user_n} 🤖{asst_n}")
        stats_hint = "\n".join(file_details)
        if skipped_files:
            stats_hint += f"\n\n⚠ 跳过 {len(skipped_files)} 个文件：\n" + "\n".join(f"  • {s}" for s in skipped_files)

        # ── 禁用按钮，显示状态 ─────────────────────────────
        self.btn_export.configure(text="导出中...", state="disabled")
        self.configure(cursor="watch")

        # ── 后台线程：仅生成 HTML 和写文件（不再读文件）───
        def do_generate():
            try:
                html_content = _generate_export_html(all_sessions, directory, options)
                Path(save_path).write_text(html_content, encoding='utf-8')

                # 预先捕获变量值（避免延迟求值的闭包问题）
                _session_count = len(all_sessions)
                _file_count = len(files)
                _stats = stats_hint
                self.after(0, lambda sc=_session_count, fc=_file_count, sh=_stats:
                           self._on_export_done(True, save_path, sc, fc, hint=sh))
            except Exception as e:
                _err_msg = str(e)
                self.after(0, lambda em=_err_msg:
                           self._on_export_done(False, "", 0, 0, error=em))

        threading.Thread(target=do_generate, daemon=True).start()

    def _on_export_done(self, ok: bool, save_path: str, session_count: int, file_count: int, error: str = "", hint: str = ""):
        self.configure(cursor="")
        self.btn_export.configure(text="📄 导出对话", state="normal")

        if ok:
            msg = (
                f"对话已导出为 HTML 文件！\n\n"
                f"📁 会话数：{session_count}\n"
                f"📄 文件数：{file_count}\n"
                f"💾 保存至：{save_path}"
                f"{hint}\n\n"
                f"是否立即在浏览器中打开？"
            )
            ok = messagebox.askyesno("导出成功", msg)
            if ok:
                os.startfile(save_path)
        else:
            messagebox.showerror("导出失败", f"生成 HTML 文件时出错：\n{error}")

    # ── 配置列表渲染 ─────────────────────────────────────────

    def _load_data(self):
        self.profiles = ConfigManager.load_profiles()
        self.current_env = ConfigManager.load_env()
        self.launch_history = ConfigManager.load_launch_history()
        self.current_mode = ConfigManager.load_default_mode()
        self._refresh_list()
        self._show_current_status()
        self._refresh_launch_history()

    def _refresh_list(self):
        for w in self.listbox_frame.winfo_children():
            w.destroy()
        self._list_frames.clear()

        if not self.profiles:
            empty = ctk.CTkLabel(
                self.listbox_frame,
                text="还没有保存的配置\n点击下方 [+ 新建] 添加",
                font=(FONT_FAMILY, 12),
                text_color=COLORS["text_muted"],
                justify="center",
            )
            empty.pack(expand=True, fill="both", pady=50)
            return

        for i, profile in enumerate(self.profiles):
            self._create_list_item(i, profile)

    def _create_list_item(self, index: int, profile: ModelProfile):
        card = ctk.CTkFrame(self.listbox_frame, corner_radius=6, height=48,
                            fg_color=COLORS["bg_card"])
        card.pack(fill="x", padx=2, pady=2)
        card.pack_propagate(False)
        card._default_fg = card.cget("fg_color")

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=5)

        name_lbl = ctk.CTkLabel(
            inner,
            text=profile.name,
            font=(FONT_FAMILY, 12, "bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        )
        name_lbl.pack(anchor="w")

        model_lbl = ctk.CTkLabel(
            inner,
            text=profile.model,
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_muted"],
            anchor="w",
        )
        model_lbl.pack(anchor="w")

        # 绑定点击
        for w in (card, inner, name_lbl, model_lbl):
            w.bind("<Button-1>", lambda e, idx=index: self._on_select(idx))

        # 鼠标悬停效果
        def on_enter(e, f=card):
            if self.selected_index != index:
                f.configure(fg_color=COLORS["bg_hover"])
        def on_leave(e, f=card):
            if self.selected_index != index:
                f.configure(fg_color=f._default_fg)
        for w in (card, inner, name_lbl, model_lbl):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

        self._list_frames[index] = card

        if self.selected_index == index:
            self._highlight_frame(card, True)

    def _highlight_frame(self, frame, selected: bool):
        if selected:
            frame.configure(fg_color=COLORS["bg_hover"], border_width=1,
                           border_color=COLORS["accent"])
        else:
            frame.configure(fg_color=frame._default_fg, border_width=0)

    def _on_select(self, index: int):
        if self.selected_index == index:
            return
        # 取消旧选中
        if self.selected_index is not None and self.selected_index in self._list_frames:
            self._highlight_frame(self._list_frames[self.selected_index], False)
        # 选中新项
        self.selected_index = index
        if index in self._list_frames:
            self._highlight_frame(self._list_frames[index], True)
        self._show_detail(index)

    # ── 详情展示 ─────────────────────────────────────────────

    def _show_detail(self, index: int):
        if index < 0 or index >= len(self.profiles):
            return

        profile = self.profiles[index]
        self.detail_placeholder.place_forget()

        # 标题和模型标签
        self.detail_title.configure(text=profile.name)
        self.detail_title._show = True
        self.detail_model_badge.configure(text=profile.model)
        self.detail_model_badge._show = True

        # 分隔线
        for k in ("_sep1", "_sep2"):
            self.detail_widgets[k][0]._show = True

        # 字段值
        for key in ["base_url", "api_key", "notes"]:
            lbl, val = self.detail_widgets[key]
            lbl._show = True
            val._show = True
            text = getattr(profile, key, "")
            if key == "api_key" and text:
                text = text[:10] + "…" + text[-6:] if len(text) > 16 else "****" + text[-6:]
            if key == "notes" and not text:
                text = "—"
            val.configure(text=text)

        for key in ["created_at", "updated_at"]:
            lbl, val = self.detail_widgets[key]
            lbl._show = True
            val._show = True
            text = getattr(profile, key, "")
            if not text:
                text = "—"
            val.configure(text=text)

        self._check_is_active(profile)

        self.btn_edit.configure(state="normal")
        self.btn_delete.configure(state="normal")
        self.btn_apply.configure(state="normal")

    def _check_is_active(self, profile: ModelProfile):
        """检查此配置是否与当前 .claude.json 中的 env 一致"""
        current = self.current_env
        match = (
            current.get("ANTHROPIC_BASE_URL", "") == profile.base_url
            and current.get("ANTHROPIC_AUTH_TOKEN", "") == profile.api_key
            and current.get("ANTHROPIC_MODEL", "") == profile.model
        )
        if match:
            self.btn_apply.configure(
                text=f"{self.icons['apply']}  已激活 ✓",
                fg_color=COLORS["bg_hover"],
                hover_color=COLORS["bg_hover"],
                state="disabled",
            )
        else:
            self.btn_apply.configure(
                text=f"{self.icons['apply']}  应用配置",
                fg_color=COLORS["success"],
                hover_color=COLORS["success_hover"],
                state="normal",
            )

    def _show_current_status(self):
        env = self.current_env
        model = env.get("ANTHROPIC_MODEL", "未设置")
        base = env.get("ANTHROPIC_BASE_URL", "")
        short_base = base.replace("https://", "").split("/")[0] if base else "默认"
        self.status_label.configure(text=f"当前模型：{model}")
        self.status_badge.configure(text=short_base)
        # 更新模式选择器
        mode_info = EXECUTION_MODES.get(self.current_mode, EXECUTION_MODES["default"])
        self.mode_combo.set(mode_info["label"])
        self.mode_desc_label.configure(text=mode_info["desc"])
        self._update_apply_button()

    # ── 执行模式切换 ─────────────────────────────────────────────

    def _update_apply_button(self):
        """根据当前选中模式是否等于已保存模式，更新应用按钮状态"""
        combo_label = self.mode_combo.get()
        selected_key = self._mode_label_to_key.get(combo_label)
        if selected_key == self.current_mode:
            self.btn_apply_mode.configure(
                text="已生效 ✓",
                fg_color=COLORS["bg_hover"],
                hover_color=COLORS["bg_hover"],
                text_color=COLORS["success"],
                state="disabled",
            )
        else:
            self.btn_apply_mode.configure(
                text="应用",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                text_color=COLORS["text_primary"],
                state="normal",
            )

    def _on_mode_changed(self, selected_label: str):
        """模式下拉框选择变更回调 — 仅预览，不自动保存"""
        mode_key = self._mode_label_to_key.get(selected_label)
        if mode_key is None:
            return
        mode_info = EXECUTION_MODES.get(mode_key, EXECUTION_MODES["default"])
        self.mode_desc_label.configure(text=mode_info["desc"])
        self._update_apply_button()

    def _on_apply_mode(self):
        """点击应用按钮，将选中的模式写入 settings.json"""
        combo_label = self.mode_combo.get()
        mode_key = self._mode_label_to_key.get(combo_label)
        if mode_key is None or mode_key == self.current_mode:
            return
        # 保存
        ok = ConfigManager.save_default_mode(mode_key)
        if ok:
            self.current_mode = mode_key
            self.mode_desc_label.configure(
                text=f"✓ 已应用！{EXECUTION_MODES[mode_key]['desc']}",
            )
            self._update_apply_button()
            # 3 秒后恢复描述文字颜色
            self.after(3000, lambda: self.mode_desc_label.configure(
                text=EXECUTION_MODES[self.current_mode]["desc"]
            ))
        else:
            self.mode_desc_label.configure(
                text="⚠ 保存失败，请检查文件权限",
                text_color=COLORS["danger"],
            )

    # ── 操作对话框 ───────────────────────────────────────────

    def _on_add(self):
        dialog = ProfileDialog(self, title="新建配置", profiles=self.profiles)
        if dialog.result:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            profile = ModelProfile(
                name=dialog.result["name"],
                base_url=dialog.result["base_url"],
                api_key=dialog.result["api_key"],
                model=dialog.result["model"],
                notes=dialog.result.get("notes", ""),
                created_at=now,
                updated_at=now,
            )
            self.profiles.append(profile)
            ConfigManager.save_profiles(self.profiles)
            self._refresh_list()
            self._on_select(len(self.profiles) - 1)
            self._show_current_status()

    def _on_edit(self):
        if self.selected_index is None:
            return
        profile = self.profiles[self.selected_index]
        dialog = ProfileDialog(
            self, title="编辑配置", initial=profile.to_dict(), profiles=self.profiles
        )
        if dialog.result:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for k, v in dialog.result.items():
                setattr(self.profiles[self.selected_index], k, v)
            self.profiles[self.selected_index].updated_at = now
            ConfigManager.save_profiles(self.profiles)
            self._refresh_list()
            self._show_detail(self.selected_index)
            self._show_current_status()

    def _on_delete(self):
        if self.selected_index is None:
            return
        profile = self.profiles[self.selected_index]
        ok = messagebox.askyesno(
            "确认删除",
            f'确定要删除配置「{profile.name}」吗？\n\n模型：{profile.model}',
            icon="warning",
        )
        if ok:
            self.profiles.pop(self.selected_index)
            self.selected_index = None
            ConfigManager.save_profiles(self.profiles)
            self._refresh_list()
            self._hide_detail()
            self.btn_edit.configure(state="disabled")
            self.btn_delete.configure(state="disabled")
            self.btn_apply.configure(state="disabled")

    def _hide_detail(self):
        self.detail_placeholder.place(relx=0.5, rely=0.45, anchor="center")
        if hasattr(self, 'detail_title'):
            self.detail_title._show = False
            self.detail_model_badge._show = False
        for key in self.detail_widgets:
            for w in self.detail_widgets[key]:
                if hasattr(w, "_show"):
                    w._show = False

    def _on_apply(self):
        if self.selected_index is None:
            return
        profile = self.profiles[self.selected_index]

        env = {
            "ANTHROPIC_BASE_URL": profile.base_url,
            "ANTHROPIC_AUTH_TOKEN": profile.api_key,
            "ANTHROPIC_MODEL": profile.model,
        }

        # 禁用按钮防连点，显示加载状态
        self.btn_apply.configure(text="应用配置中...", state="disabled")
        self.configure(cursor="watch")

        def do_apply():
            ok = ConfigManager.apply_env(env)
            self.after(0, lambda: self._on_apply_done(ok, env, profile))

        threading.Thread(target=do_apply, daemon=True).start()

    def _on_apply_done(self, ok: bool, env: dict, profile: ModelProfile):
        self.configure(cursor="")
        if ok:
            self.current_env = env
            self._show_current_status()
            self._check_is_active(profile)

            # 自动启动 Claude
            if self._auto_launch.get():
                directory = self.launcher_dir_entry.get().strip()
                if directory and os.path.isdir(directory):
                    self._launch_claude(directory)

            messagebox.showinfo(
                "应用成功",
                f'配置「{profile.name}」已应用\n\n'
                f'模型：{profile.model}\n'
                f'API：{profile.base_url}\n\n'
                f'请手动重启 Claude Code 以使新配置生效。',
            )
        else:
            self.btn_apply.configure(
                text=f"{self.icons['apply']}  应用配置",
                fg_color=COLORS["success"],
                hover_color="#16a34a",
                state="normal",
            )
            messagebox.showerror("应用失败", "写入 .claude.json 失败，请检查文件权限。")

    def _on_dashboard(self):
        if not self.profiles:
            messagebox.showinfo("提示", "还没有保存的配置，请先添加配置。")
            return
        BalanceDashboard(self, self.profiles)

    @staticmethod
    def _open_backup():
        """打开备份目录"""
        if BACKUP_DIR.exists():
            os.startfile(str(BACKUP_DIR))
        else:
            messagebox.showinfo("提示", "备份目录为空，还没有备份文件。")

    @staticmethod
    def _open_config():
        """用记事本打开 .claude.json"""
        if CLAUDE_JSON.exists():
            os.startfile(str(CLAUDE_JSON))

    # ── 主题同步 ─────────────────────────────────────────────

    def _theme_check_loop(self):
        """每 1.5 秒检测系统主题变化并自动同步"""
        if _sync_colors():
            self._last_appearance = _appearance_mode
            self._reapply_theme()
        self.after(1500, self._theme_check_loop)

    def _update_widget_color(self, widget, attr: str, color_key: str):
        """更新单个 widget 的颜色属性"""
        try:
            widget.configure(**{attr: COLORS[color_key]})
        except Exception:
            pass

    def _reapply_theme(self):
        """重新应用所有主题颜色到已有 widget"""
        c = COLORS

        # 根窗口
        self.configure(fg_color=c["bg_dark"])

        # 状态栏
        self.status_frame.configure(fg_color=c["bg_card"])
        self.status_label.configure(text_color=c["text_primary"])
        self.status_badge.configure(text_color=c["accent_light"], fg_color=c["bg_hover"])
        # 模式选择器
        self.mode_label.configure(text_color=c["text_muted"])
        self.mode_combo.configure(
            fg_color=c["bg_input"],
            border_color=c["border"],
            button_color=c["bg_hover"],
            button_hover_color=c["accent"],
        )
        self.mode_desc_label.configure(text_color=c["text_muted"])
        self._update_apply_button()  # 恢复按钮状态

        # Tabview
        self.tabview.configure(fg_color=c["bg_dark"])

        # 左侧列表
        self.list_frame.configure(fg_color=c["bg_card"])
        self.list_header.configure(text_color=c["text_secondary"])

        # 右侧详情面板
        self.detail_frame.configure(fg_color=c["bg_card"])
        self.detail_placeholder.configure(text_color=c["text_muted"])
        if hasattr(self, "detail_title") and getattr(self.detail_title, "_show", False):
            self.detail_title.configure(text_color=c["text_primary"])
            self.detail_model_badge.configure(fg_color=c["bg_hover"])
            for key in ("_sep1", "_sep2"):
                self.detail_widgets[key][0].configure(fg_color=c["border"])
            for key in ("base_url", "api_key", "notes", "created_at", "updated_at"):
                lbl, val = self.detail_widgets[key]
                lbl.configure(text_color=c["text_muted"])
                val.configure(text_color=c["text_primary"] if key != "created_at" and key != "updated_at" else c["text_secondary"])

        # 操作栏
        self.action_frame.configure(fg_color=c["bg_card"])

        # 按钮 - 保持状态感知
        self._reapply_button_colors()

        # Launcher tab
        self.dir_frame.configure(fg_color=c["bg_card"])
        self.ctrl_frame.configure(fg_color=c["bg_card"])
        self.launcher_dir_entry.configure(fg_color=c["bg_input"], border_color=c["border"])
        self.launcher_label_entry.configure(fg_color=c["bg_input"], border_color=c["border"])
        self.auto_launch_check.configure(text_color=c["text_secondary"], border_color=c["border"])

        # 刷新动态内容
        self._refresh_list()
        self._refresh_launch_history()

        # 恢复详情显示
        if self.selected_index is not None:
            self._show_detail(self.selected_index)

    def _reapply_button_colors(self):
        """更新所有按钮的主题颜色，保持 disabled 状态"""
        c = COLORS

        button_specs = [
            (self.btn_add, c["accent"], c["accent_hover"]),
            (self.btn_edit, c["bg_hover"], c["bg_input"]),
            (self.btn_delete, c["bg_hover"], c["danger"]),
            (self.btn_backup, "transparent", c["bg_hover"]),
            (self.btn_dashboard, c["warning"], c["warning_hover"]),
            (self.btn_open_config, "transparent", c["bg_hover"]),
        ]

        for btn, fg, hover in button_specs:
            state = btn.cget("state")
            if state == "normal":
                btn.configure(fg_color=fg, hover_color=hover, text_color=c["text_primary"])
            elif state == "disabled":
                btn.configure(text_color_disabled=c["text_muted"])
            if btn is self.btn_backup or btn is self.btn_open_config:
                btn.configure(text_color=c["text_muted"], border_color=c["border"])

        # 应用按钮保持当前激活状态
        if self.btn_apply.cget("state") == "normal":
            self.btn_apply.configure(fg_color=c["success"], hover_color=c["success_hover"])

        # Launcher 中的浏览按钮
        self.btn_launch.configure(fg_color=c["accent"], hover_color=c["accent_hover"])
        if self.btn_export.cget("state") == "normal":
            self.btn_export.configure(fg_color=c["warning"], hover_color=c["warning_hover"])
        # 浏览按钮
        for child in self.dir_frame.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(text_color=c["text_primary"])

    def _on_close(self):
        self.destroy()


# ─── 配置编辑对话框 ──────────────────────────────────────────
class ProfileDialog(ctk.CTkToplevel):
    def __init__(self, parent, title="配置", initial: Optional[dict] = None, profiles: list[ModelProfile] = None):
        super().__init__(parent)

        self.title(title)
        self.geometry("520x480")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: Optional[dict] = None
        self.initial = initial or {}
        self.profiles = profiles or []

        self._build()
        self._fill_initial()

        # 居中
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        self.wait_window()

    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.configure(fg_color=COLORS["bg_dark"])

        # 从已有配置中提取历史值（去重）
        url_history = list(set(p.base_url for p in self.profiles if p.base_url))
        model_history = list(set(p.model for p in self.profiles if p.model))

        fields = [
            ("name", "配置名称 *", "例如：DeepSeek V4", "entry", []),
            ("base_url", "API 地址 *", "例如：https://api.deepseek.com/anthropic", "combo", url_history),
            ("api_key", "API 密钥 *", "sk-...", "entry", []),
            ("model", "模型名称 *", "例如：deepseek-v4-flash", "combo", model_history),
            ("notes", "备注", "可选备注信息", "entry", []),
        ]

        self.entries = {}
        for i, (key, label, placeholder, widget_type, options) in enumerate(fields):
            lbl = ctk.CTkLabel(
                self, text=label, font=(FONT_FAMILY, 12, "bold"),
                text_color=COLORS["text_secondary"], anchor="w",
            )
            lbl.grid(row=i, column=0, sticky="w", padx=(20, 8), pady=(16, 0))

            if widget_type == "combo":
                entry = ctk.CTkComboBox(
                    self,
                    values=options,
                    font=(FONT_FAMILY, 13),
                    height=36,
                    fg_color=COLORS["bg_input"],
                    border_color=COLORS["border"],
                    button_color=COLORS["bg_hover"],
                    button_hover_color=COLORS["accent"],
                    corner_radius=6,
                )
                entry.set("")
            else:
                entry_kwargs = {
                    "placeholder_text": placeholder,
                    "font": (FONT_FAMILY, 13),
                    "height": 36,
                    "fg_color": COLORS["bg_input"],
                    "border_color": COLORS["border"],
                    "corner_radius": 6,
                }
                if key == "api_key":
                    entry_kwargs["show"] = "*"
                entry = ctk.CTkEntry(self, **entry_kwargs)
            entry.grid(row=i, column=1, sticky="ew", padx=(0, 20), pady=(16, 0))
            self.entries[key] = entry

        # 提示文本
        tip = ctk.CTkLabel(
            self,
            text="* 为必填项",
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_muted"],
        )
        tip.grid(row=len(fields), column=0, columnspan=2, sticky="w", padx=20, pady=(8, 0))

        # 按钮
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(
            row=len(fields) + 1, column=0, columnspan=2,
            sticky="ew", padx=20, pady=(20, 16),
        )
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            btn_frame, text="取消", command=self.destroy,
            font=(FONT_FAMILY, 13),
            fg_color=COLORS["bg_hover"], hover_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            corner_radius=6,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            btn_frame, text="保存", command=self._on_save,
            font=(FONT_FAMILY, 13, "bold"),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            corner_radius=6,
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _fill_initial(self):
        if not self.initial:
            return
        for key, entry in self.entries.items():
            if key in self.initial and self.initial[key]:
                if isinstance(entry, ctk.CTkComboBox):
                    entry.set(self.initial[key])
                    # 如果当前值不在下拉列表中，追加进去
                    if self.initial[key] and self.initial[key] not in entry.cget("values"):
                        current_vals = list(entry.cget("values"))
                        current_vals.insert(0, self.initial[key])
                        entry.configure(values=current_vals)
                else:
                    entry.insert(0, self.initial[key])

    def _on_save(self):
        data = {}
        for key, entry in self.entries.items():
            val = entry.get().strip()
            if key != "notes":
                data[key] = val
            else:
                data[key] = val

        # 验证
        errors = []
        if not data.get("name"):
            errors.append("配置名称不能为空")
        if not data.get("base_url"):
            errors.append("API 地址不能为空")
        if not data.get("api_key"):
            errors.append("API 密钥不能为空")
        if not data.get("model"):
            errors.append("模型名称不能为空")

        if errors:
            messagebox.showwarning("输入不完整", "\n".join(errors), parent=self)
            return

        self.result = data
        self.destroy()


# ─── 导出选项对话框 ──────────────────────────────────────────

EXPORT_ITEMS = [
    ("user", "👤 用户消息", "你的提问和输入"),
    ("assistant", "🤖 Claude 回复", "Claude 的文字回复"),
    ("thinking", "💭 思考过程", "Claude 的推理思考"),
    ("tool_use", "🔧 工具调用", "Read / Edit / Bash 等"),
    ("tool_result", "📋 工具返回", "工具执行的结果"),
    ("system", "⚙ 系统消息", "模式 / 权限切换等"),
]


class ExportOptionsDialog(ctk.CTkToplevel):
    """导出前的内容选项对话框"""

    def __init__(self, parent):
        super().__init__(parent)

        self.title("导出选项")
        self.geometry("400x480")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: dict = None
        self._checks: dict[str, ctk.BooleanVar] = {}

        self._build()

        # 居中
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        self.wait_window()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.configure(fg_color=COLORS["bg_dark"])

        # 标题
        ctk.CTkLabel(
            self, text="选择要导出的内容",
            font=(FONT_FAMILY, 14, "bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(20, 4))

        ctk.CTkLabel(
            self, text="取消勾选的内容将不会出现在 HTML 中",
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_muted"],
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 12))

        # 可滚动列表区
        list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                            corner_radius=8,
                                            scrollbar_button_color=COLORS["accent"],
                                            scrollbar_button_hover_color=COLORS["accent_hover"])
        list_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=4)
        list_frame.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        for i, (key, label, desc) in enumerate(EXPORT_ITEMS):
            var = ctk.BooleanVar(value=True)
            self._checks[key] = var

            row_frame = ctk.CTkFrame(list_frame, fg_color=COLORS["bg_card"],
                                     corner_radius=8)
            row_frame.pack(fill="x", pady=3)
            row_frame.grid_columnconfigure(1, weight=1)

            cb = ctk.CTkCheckBox(
                row_frame, text="", variable=var,
                width=22, height=22,
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                border_color=COLORS["border"],
                checkmark_color=COLORS["text_primary"],
            )
            cb.grid(row=0, column=0, sticky="w", padx=(10, 4), pady=8)

            ctk.CTkLabel(
                row_frame, text=label,
                font=(FONT_FAMILY, 12, "bold"),
                text_color=COLORS["text_primary"],
                anchor="w",
            ).grid(row=0, column=1, sticky="w", pady=(8, 0))

            ctk.CTkLabel(
                row_frame, text=desc,
                font=(FONT_FAMILY, 10),
                text_color=COLORS["text_muted"],
                anchor="w",
            ).grid(row=1, column=1, sticky="w", pady=(0, 8))

        # 底部按钮
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 16))
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            btn_frame, text="全选 / 全不选",
            command=self._toggle_all,
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            corner_radius=6,
            height=34,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

        ctk.CTkButton(
            btn_frame, text="确认导出",
            command=self._on_confirm,
            font=(FONT_FAMILY, 13, "bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=6,
            height=34,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self._toggle_state = True  # 当前是全选状态

    def _toggle_all(self):
        self._toggle_state = not self._toggle_state
        for var in self._checks.values():
            var.set(self._toggle_state)

    def _on_confirm(self):
        self.result = {key: var.get() for key, var in self._checks.items()}
        self.destroy()


# ─── 启动 ────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ModelSwitcherApp()
    app.mainloop()
