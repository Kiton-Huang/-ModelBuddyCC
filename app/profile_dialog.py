"""
配置编辑对话框
"""
from typing import Optional
import customtkinter as ctk
from tkinter import messagebox

from app.theme import COLORS, FONT_FAMILY
from app.models import ModelProfile


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
            data[key] = val

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
