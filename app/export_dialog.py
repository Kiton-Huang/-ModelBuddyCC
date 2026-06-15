"""
导出选项对话框
"""
import customtkinter as ctk
from datetime import datetime

from app.theme import COLORS, FONT_FAMILY


EXPORT_ITEMS = [
    ("user", "👤 用户消息", "你的提问和输入"),
    ("assistant", "🤖 Claude 回复", "Claude 的文字回复"),
    ("thinking", "💭 思考过程", "Claude 的推理思考"),
    ("tool_use", "🔧 工具调用", "Read / Edit / Bash 等"),
    ("tool_result", "📋 工具返回", "工具执行的结果"),
    ("system", "⚙ 系统消息", "模式 / 权限切换等"),
]


def _extract_session_preview(messages: list[dict]) -> dict:
    """从会话消息中提取预览信息：第一条用户消息、时间、各类消息计数"""
    first_user_msg = ""
    first_ts = ""
    counts = {"user": 0, "assistant": 0, "thinking": 0, "tool_use": 0,
              "tool_result": 0, "system": 0}

    for m in messages:
        msg_type = m.get('type', '')
        if msg_type in counts:
            counts[msg_type] += 1
        elif msg_type in ('mode', 'permission-mode'):
            counts["system"] += 1

        if not first_ts:
            ts = m.get('timestamp', '')
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    first_ts = dt.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    first_ts = ts[:16] if len(ts) >= 16 else ts

        if not first_user_msg:
            content = m.get('message', {}).get('content', '')
            if isinstance(content, str) and content.strip():
                first_user_msg = content.strip()
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text = block.get('text', '').strip()
                        if text:
                            first_user_msg = text
                            break

    # 截断预览文本
    if len(first_user_msg) > 100:
        first_user_msg = first_user_msg[:100] + '…'

    return {
        "preview": first_user_msg,
        "timestamp": first_ts,
        "counts": counts,
    }


class ExportOptionsDialog(ctk.CTkToplevel):
    """导出前的内容 + 对话选择对话框"""

    def __init__(self, parent, sessions: list):
        """
        sessions: list of (filepath, messages) tuples
        """
        super().__init__(parent)

        self.title("导出选项")
        self.geometry("560x640")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: dict = None
        self._checks: dict[str, ctk.BooleanVar] = {}
        self._session_vars: list[ctk.BooleanVar] = []
        self._sessions = sessions

        # 预计算所有会话预览
        self._previews = [_extract_session_preview(msgs) for _, msgs in sessions]

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

        # ── 标题 ──
        ctk.CTkLabel(
            self, text="导出选项",
            font=(FONT_FAMILY, 14, "bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(20, 2))

        ctk.CTkLabel(
            self, text="勾选要导出的内容类型和对话",
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_muted"],
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 8))

        # ── 内容类型选择 ──
        type_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=8)
        type_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        type_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(
            type_frame, text="内容类型",
            font=(FONT_FAMILY, 11, "bold"),
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 4))

        for i, (key, label, desc) in enumerate(EXPORT_ITEMS):
            col = i % 2
            row = 1 + i // 2
            var = ctk.BooleanVar(value=True)
            self._checks[key] = var

            item_frame = ctk.CTkFrame(type_frame, fg_color="transparent")
            item_frame.grid(row=row, column=col, sticky="ew", padx=8, pady=2)

            cb = ctk.CTkCheckBox(
                item_frame, text="", variable=var,
                width=20, height=20,
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                border_color=COLORS["border"],
                checkmark_color=COLORS["text_primary"],
            )
            cb.pack(side="left", padx=(4, 4))

            ctk.CTkLabel(
                item_frame, text=label,
                font=(FONT_FAMILY, 11, "bold"),
                text_color=COLORS["text_primary"],
            ).pack(side="left")

        self._toggle_type_state = True

        # ── 对话选择标题栏 ──
        conv_header = ctk.CTkFrame(self, fg_color="transparent")
        conv_header.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 2))
        conv_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            conv_header, text=f"选择对话（共 {len(self._sessions)} 个）",
            font=(FONT_FAMILY, 12, "bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            conv_header, text="全选",
            command=self._select_all_sessions,
            width=50, height=24,
            font=(FONT_FAMILY, 10),
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent"],
            text_color=COLORS["text_primary"],
            corner_radius=4,
        ).grid(row=0, column=1, sticky="e", padx=(2, 2))

        ctk.CTkButton(
            conv_header, text="全不选",
            command=self._deselect_all_sessions,
            width=50, height=24,
            font=(FONT_FAMILY, 10),
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent"],
            text_color=COLORS["text_primary"],
            corner_radius=4,
        ).grid(row=0, column=2, sticky="e")

        # ── 对话列表（可滚动） ──
        self._conv_list_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            corner_radius=8,
            scrollbar_button_color=COLORS["accent"],
            scrollbar_button_hover_color=COLORS["accent_hover"],
        )
        self._conv_list_frame.grid(row=4, column=0, sticky="nsew", padx=12, pady=4)
        self._conv_list_frame.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._build_session_items()

        # ── 底部按钮 ──
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=0, sticky="ew", padx=20, pady=(8, 16))
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            btn_frame, text="取消",
            command=self.destroy,
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["danger"],
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

    def _build_session_items(self):
        """为每个会话创建带预览的选择卡片"""
        for idx, (fp, msgs) in enumerate(self._sessions):
            p = self._previews[idx]
            var = ctk.BooleanVar(value=True)
            self._session_vars.append(var)

            # 卡片容器
            card = ctk.CTkFrame(self._conv_list_frame, fg_color=COLORS["bg_card"],
                                corner_radius=6)
            card.pack(fill="x", pady=2)
            card.grid_columnconfigure(1, weight=1)

            # 复选框
            cb = ctk.CTkCheckBox(
                card, text="", variable=var,
                width=20, height=20,
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                border_color=COLORS["border"],
                checkmark_color=COLORS["text_primary"],
            )
            cb.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(10, 4), pady=8)

            # 第一行：时间 + 统计
            info_parts = []
            if p["timestamp"]:
                info_parts.append(f"🕐 {p['timestamp']}")
            cnt = p["counts"]
            stat_parts = []
            if cnt["user"]:
                stat_parts.append(f"👤{cnt['user']}")
            if cnt["assistant"]:
                stat_parts.append(f"🤖{cnt['assistant']}")
            if cnt["thinking"]:
                stat_parts.append(f"💭{cnt['thinking']}")
            if cnt["tool_use"]:
                stat_parts.append(f"🔧{cnt['tool_use']}")
            info_parts.append(" · ".join(stat_parts) if stat_parts else "空对话")

            ctk.CTkLabel(
                card, text="  ".join(info_parts),
                font=(FONT_FAMILY, 10),
                text_color=COLORS["text_secondary"],
                anchor="w",
            ).grid(row=0, column=1, sticky="w", padx=(0, 10), pady=(8, 0))

            # 第二行：第一条用户消息预览
            preview_text = p["preview"] if p["preview"] else "（无用户消息）"
            ctk.CTkLabel(
                card, text=preview_text,
                font=(FONT_FAMILY, 11),
                text_color=COLORS["text_muted"] if not p["preview"] else COLORS["text_primary"],
                anchor="w",
                wraplength=460,
                justify="left",
            ).grid(row=1, column=1, sticky="w", padx=(0, 10), pady=(2, 8))

            # 点击卡片切换复选框
            for child in card.winfo_children():
                if not isinstance(child, ctk.CTkCheckBox):
                    child.bind("<Button-1>", lambda e, v=var: v.set(not v.get()))

    def _select_all_sessions(self):
        for var in self._session_vars:
            var.set(True)

    def _deselect_all_sessions(self):
        for var in self._session_vars:
            var.set(False)

    def _on_confirm(self):
        selected = [i for i, var in enumerate(self._session_vars) if var.get()]
        if not selected:
            # 未选中任何对话，视为取消
            self.destroy()
            return
        self.result = {
            "content_options": {key: var.get() for key, var in self._checks.items()},
            "selected_indices": selected,
        }
        self.destroy()
