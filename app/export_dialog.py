"""
导出选项对话框
"""
import customtkinter as ctk

from app.theme import COLORS, FONT_FAMILY


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

        self._toggle_state = True

    def _toggle_all(self):
        self._toggle_state = not self._toggle_state
        for var in self._checks.values():
            var.set(self._toggle_state)

    def _on_confirm(self):
        self.result = {key: var.get() for key, var in self._checks.items()}
        self.destroy()
