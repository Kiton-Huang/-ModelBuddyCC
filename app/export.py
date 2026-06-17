"""
对话导出 — JSONL 解析 + HTML 生成
"""
import json
import re
import html as _html
from datetime import datetime
from pathlib import Path

from app.constants import TRANSCRIPTS_DIR


def _directory_to_project_key(directory: str) -> str:
    """将目录路径转换为 Claude Code 的项目存储键"""
    directory = directory.replace('/', '\\')
    result = []
    for char in directory:
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
                if msg_type in ('user', 'assistant', 'mode', 'permission-mode'):
                    messages.append(msg)
            except json.JSONDecodeError:
                continue
    return messages


def _tool_one_liner(tool_name: str, tool_input: dict) -> str:
    """从工具参数中提取一行关键描述"""
    if not tool_input:
        return ''
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
    for k, v in tool_input.items():
        if isinstance(v, str) and v:
            v = v.replace('\n', ' ').strip()
            if len(v) > 60:
                v = v[:60] + '...'
            return f': {v}'
    return ''


def _format_code_blocks(text: str) -> str:
    """将 ``` 代码块转换为 HTML"""
    def replace_code_block(m):
        lang = m.group(1) or ''
        code = m.group(2)
        lang_class = f' class="language-{_html.escape(lang)}"' if lang else ''
        return f'<pre{lang_class}><code>{code}</code></pre>'
    return re.sub(r'```(\w*)\n?(.*?)```', replace_code_block, text, flags=re.DOTALL)


def _format_inline_code(text: str) -> str:
    """将 ` 行内代码转换为 HTML"""
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


def _get_user_preview(msg: dict) -> str:
    """从用户消息中提取简短预览文本（用于导航栏）"""
    content = msg.get('message', {}).get('content', '')
    text = ''
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'text':
                text = block.get('text', '').strip()
                break
    text = text.replace('\n', ' ').strip()
    if len(text) > 50:
        text = text[:50] + '…'
    return text


def _render_content_blocks(blocks: list, is_assistant: bool = False, options: dict = None) -> str:
    """将消息内容块渲染为 HTML，options 控制显示哪些内容类型"""
    if options is None:
        options = {}
    parts = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get('type', '')
        if block_type == 'thinking' and not options.get('thinking', True):
            continue
        if block_type == 'tool_use' and not options.get('tool_use', True):
            continue
        if block_type == 'tool_result' and not options.get('tool_result', True):
            continue
        if block_type == 'text':
            text = block.get('text', '')
            if text:
                text = _html.escape(text)
                text = _format_code_blocks(text)
                text = _format_inline_code(text)
                parts.append(f'<div class="msg-text">{text}</div>')
        elif block_type == 'thinking':
            thinking = block.get('thinking', '')
            if thinking:
                thinking_escaped = _html.escape(thinking)
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
            if result_str:
                if len(result_str) > 300:
                    short = result_str[:300] + '...'
                    tool_id = f'tool-{id(block)}'
                    parts.append(
                        f'<div class="tool-block tool-result">'
                        f'<div class="tool-header">'
                        f'<span class="tool-label">📋 工具返回</span>'
                        f'<span class="tool-len">({len(result_str)} 字符)</span>'
                        f'</div>'
                        f'<div class="tool-body tool-collapsed" id="{tool_id}">'
                        f'<div class="tool-preview">{short}</div>'
                        f'<div class="tool-full" style="display:none;">{result_str}</div>'
                        f'</div>'
                        f'<button class="tool-toggle" onclick="toggleToolResult(\'{tool_id}\', this)">📋 展开全部</button>'
                        f'</div>'
                    )
                else:
                    parts.append(
                        f'<div class="tool-block tool-result">'
                        f'<div class="tool-header">'
                        f'<span class="tool-label">📋 工具返回</span>'
                        f'<span class="tool-len">({len(result_str)} 字符)</span>'
                        f'</div>'
                        f'<div class="tool-body">{result_str}</div>'
                        f'</div>'
                    )
    return '\n'.join(parts)


def _generate_export_html(all_sessions: list[tuple[Path, list[dict]]], directory: str, options: dict = None) -> str:
    """生成包含所有对话的 HTML 文件，options 控制导出内容"""
    if options is None:
        options = {}
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    dir_name = Path(directory).name or directory

    total_user = 0
    total_assistant = 0
    for _, msgs in all_sessions:
        for m in msgs:
            if m.get('type') == 'user':
                total_user += 1
            elif m.get('type') == 'assistant':
                total_assistant += 1

    # 导航栏数据将在渲染时收集（保证 ID 对齐）
    _nav_items = []  # (session_idx, msg_id, preview)

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
  .tool-label {{
    font-size: 10px;
    font-weight: 600;
    color: #e2e8f0;
  }}
  .tool-len {{
    font-size: 8px;
    color: #94a3b8;
    background: #1e293b;
    padding: 1px 6px;
    border-radius: 8px;
    margin-left: 6px;
  }}
  .tool-result .tool-body {{
    max-height: 400px;
  }}
  .tool-collapsed .tool-preview {{
    display: block;
  }}
  .tool-collapsed .tool-full {{
    display: none;
  }}
  .tool-expanded .tool-preview {{
    display: none;
  }}
  .tool-expanded .tool-full {{
    display: block;
  }}
  .tool-toggle {{
    display: block;
    width: 100%;
    padding: 4px 10px;
    font-size: 9px;
    font-weight: 600;
    color: #94a3b8;
    background: #1e293b;
    border: none;
    border-top: 1px solid #334155;
    cursor: pointer;
    font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
    transition: all 0.15s ease;
    text-align: center;
  }}
  .tool-toggle:hover {{
    background: #334155;
    color: #e2e8f0;
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
    .tool-toggle {{
      display: none !important;
    }}
    .tool-collapsed .tool-preview {{
      display: block !important;
    }}
    .tool-collapsed .tool-full {{
      display: none !important;
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
    #sidebar, #sidebar-toggle-btn {{ display: none !important; }}
    body {{ padding-right: 0 !important; }}
  }}
  #sidebar {{
    position: fixed;
    right: 0; top: 0;
    width: 260px;
    height: 100vh;
    background: #e2e8f0;
    border-left: 1px solid #c8cdd5;
    color: #334155;
    z-index: 1000;
    overflow-y: auto;
    box-shadow: -2px 0 8px rgba(0,0,0,0.06);
    transition: transform 0.3s ease;
    display: flex;
    flex-direction: column;
  }}
  #sidebar.hidden {{
    transform: translateX(260px);
  }}
  .sidebar-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    background: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    font-size: 13px;
    font-weight: 700;
    position: sticky;
    top: 0;
    z-index: 2;
  }}
  .sidebar-close {{
    background: none;
    border: none;
    color: #94a3b8;
    font-size: 18px;
    cursor: pointer;
    padding: 2px 8px;
    border-radius: 4px;
    line-height: 1;
    font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
  }}
  .sidebar-close:hover {{
    background: #e2e8f0;
    color: #334155;
  }}
  .sidebar-list {{
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
  }}
  .sidebar-session-label {{
    padding: 8px 14px 3px;
    font-size: 9px;
    font-weight: 700;
    color: #6366f1;
    letter-spacing: 0.5px;
  }}
  .sidebar-nav-item {{
    display: block;
    padding: 5px 14px 5px 20px;
    font-size: 11px;
    color: #475569;
    text-decoration: none;
    cursor: pointer;
    border-left: 2px solid transparent;
    transition: all 0.15s;
    line-height: 1.35;
  }}
  .sidebar-nav-item:hover {{
    background: #c8cdd5;
    color: #0f172a;
    border-left-color: #6366f1;
  }}
  .sidebar-nav-item.active {{
    color: #0f172a;
    background: #c8cdd5;
    border-left-color: #6366f1;
    font-weight: 600;
  }}
  #sidebar-toggle-btn {{
    position: fixed;
    right: 10px; top: 10px;
    z-index: 1001;
    width: 34px; height: 34px;
    background: #ffffff;
    color: #475569;
    border: 1px solid #c8cdd5;
    border-radius: 6px;
    font-size: 16px;
    cursor: pointer;
    display: none;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  }}
  #sidebar-toggle-btn:hover {{
    background: #f1f5f9;
    color: #0f172a;
  }}
  body {{
    padding-right: 270px;
    transition: padding-right 0.3s ease;
  }}
  body.sidebar-hidden {{
    padding-right: 0;
  }}
  body.sidebar-hidden #sidebar {{
    transform: translateX(260px);
  }}
  body.sidebar-hidden #sidebar-toggle-btn {{
    display: block;
  }}
</style>
</head>
<body>
<!--SIDEBAR_PLACEHOLDER-->
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

    _msg_id = 0  # 重置消息计数器用于渲染
    for session_idx, (filepath, messages) in enumerate(all_sessions):
        if not messages:
            continue

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

            if msg_type == 'user' and not options.get('user', True):
                continue
            if msg_type == 'assistant' and not options.get('assistant', True):
                continue

            role_class = msg_type

            content = msg.get('message', {}).get('content', '')
            if isinstance(content, str):
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

            _current_msg_id = _msg_id
            _msg_id += 1
            # 收集用户消息到导航栏
            if msg_type == 'user':
                _pv = _get_user_preview(msg)
                if _pv:
                    _nav_items.append((session_idx, f'msg-{_current_msg_id}', _pv))
            html += f'''
<div class="message {role_class}" id="msg-{_current_msg_id}">
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

    # ── 构建侧边栏 HTML 并替换占位符 ──
    _sidebar_html = ''
    _toggle_btn_html = ''
    if _nav_items:
        _sb = '<nav id="sidebar">\n'
        _sb += '  <div class="sidebar-header">\n'
        _sb += '    <span>📑 对话导航</span>\n'
        _sb += f'    <span class="sidebar-count">共 {len(_nav_items)} 条</span>\n'
        _sb += '    <button class="sidebar-close" onclick="toggleSidebar()" title="隐藏导航栏">✕</button>\n'
        _sb += '  </div>\n'
        _sb += '  <div class="sidebar-list">\n'
        _last_s = -1
        _item_n = 0
        for _s_idx, _mid, _prev in _nav_items:
            if _s_idx != _last_s:
                _last_s = _s_idx
                _sb += f'    <div class="sidebar-session-label">会话 #{_s_idx + 1}</div>\n'
            _item_n += 1
            _esc = _html.escape(_prev)
            _sb += f'    <a class="sidebar-nav-item" href="#{_mid}" onclick="scrollToMsg(\'{_mid}\', this)">{_item_n}. {_esc}</a>\n'
        _sb += '  </div>\n'
        _sb += '</nav>\n'
        _sidebar_html = _sb
        _toggle_btn_html = '<button id="sidebar-toggle-btn" onclick="toggleSidebar()" title="显示导航栏">📑</button>\n'
    _combined = _sidebar_html + _toggle_btn_html
    html = html.replace('<!--SIDEBAR_PLACEHOLDER-->', _combined)

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
function toggleToolResult(id, btn) {
  var el = document.getElementById(id);
  if (!el) return;
  var preview = el.querySelector('.tool-preview');
  var full = el.querySelector('.tool-full');
  var isCollapsed = el.classList.contains('tool-collapsed');
  if (isCollapsed) {
    el.classList.remove('tool-collapsed');
    el.classList.add('tool-expanded');
    if (preview) preview.style.display = 'none';
    if (full) full.style.display = 'block';
    btn.textContent = '📋 收起';
    btn.classList.add('expanded');
  } else {
    el.classList.remove('tool-expanded');
    el.classList.add('tool-collapsed');
    if (preview) preview.style.display = 'block';
    if (full) full.style.display = 'none';
    btn.textContent = '📋 展开全部';
    btn.classList.remove('expanded');
  }
}
function scrollToMsg(id, link) {
  var el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  // 高亮当前项
  document.querySelectorAll('.sidebar-nav-item.active').forEach(function(a) { a.classList.remove('active'); });
  if (link) link.classList.add('active');
  // 闪一下目标消息
  el.style.transition = 'box-shadow 0.4s ease';
  el.style.boxShadow = '0 0 0 3px #6366f1';
  setTimeout(function() { el.style.boxShadow = ''; }, 1500);
}
function toggleSidebar() {
  var body = document.body;
  var hidden = body.classList.contains('sidebar-hidden');
  if (hidden) {
    body.classList.remove('sidebar-hidden');
  } else {
    body.classList.add('sidebar-hidden');
  }
}
</script>
</body>
</html>
'''
    return html
