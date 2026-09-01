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
        self.geometry("520x620")
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

        # ── 基础字段 ──
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

        base_row = len(fields)  # = 5

        # ── 高级选项折叠按钮 ──
        self.advanced_toggle = ctk.CTkButton(
            self, text="▶ 高级选项",
            command=self._toggle_advanced,
            font=(FONT_FAMILY, 12, "bold"),
            fg_color="transparent",
            text_color=COLORS["accent"],
            hover_color=COLORS["bg_hover"],
            anchor="w",
        )
        self.advanced_toggle.grid(row=base_row, column=0, columnspan=2,
                                  sticky="w", padx=16, pady=(12, 0))

        # ── 高级选项内容（初始隐藏） ──
        self.advanced_frame = ctk.CTkFrame(self, fg_color="transparent")
        # 放在 toggle 下面，初始不显示
        self.advanced_frame.grid_rowconfigure((0, 1, 2, 3, 4), weight=0)

        adv_fields = [
            ("opus_model", "Opus 模型映射",
             "Claude Code 调用 Opus 级别任务时使用的模型"),
            ("sonnet_model", "Sonnet 模型映射",
             "Claude Code 调用 Sonnet 级别任务时使用的模型"),
            ("haiku_model", "Haiku 模型映射",
             "Claude Code 调用 Haiku 级别任务时使用的模型"),
            ("subagent_model", "子代理模型",
             "Claude Code 子代理使用的模型"),
        ]

        for j, (key, label, hint) in enumerate(adv_fields):
            ctk.CTkLabel(
                self.advanced_frame, text=label,
                font=(FONT_FAMILY, 11, "bold"),
                text_color=COLORS["text_secondary"], anchor="w",
            ).grid(row=j, column=0, sticky="w", padx=(20, 8), pady=(10, 0))

            entry = ctk.CTkComboBox(
                self.advanced_frame,
                values=model_history,
                font=(FONT_FAMILY, 13),
                height=34,
                fg_color=COLORS["bg_input"],
                border_color=COLORS["border"],
                button_color=COLORS["bg_hover"],
                button_hover_color=COLORS["accent"],
                corner_radius=6,
            )
            entry.set("")
            entry.grid(row=j, column=1, sticky="ew", padx=(0, 20), pady=(10, 0))
            self.entries[key] = entry

        # ── DeepSeek 一键预设 ──
        self.btn_preset = ctk.CTkButton(
            self, text="🪄 DeepSeek 一键预设",
            command=self._apply_deepseek_preset,
            font=(FONT_FAMILY, 12, "bold"),
            fg_color="#4c1d95",
            hover_color="#6d28d9",
            corner_radius=6,
            height=34,
        )
        # 放在 advanced_frame 下面，初始也隐藏
        self.btn_preset.grid_remove()

        # 提示文本
        tip_row = base_row + 3  # toggle + advanced_frame + btn_preset (space reserved)
        tip = ctk.CTkLabel(
            self,
            text="* 为必填项  |  高级选项中填写模型映射以充分利用 DeepSeek 推荐配置",
            font=(FONT_FAMILY, 10),
            text_color=COLORS["text_muted"],
        )
        tip.grid(row=tip_row, column=0, columnspan=2, sticky="w", padx=20, pady=(8, 0))

        # 按钮
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(
            row=tip_row + 1, column=0, columnspan=2,
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

    # ── 高级选项折叠 ──

    def _toggle_advanced(self):
        if self.advanced_frame.winfo_viewable():
            self.advanced_frame.grid_remove()
            self.btn_preset.grid_remove()
            self.advanced_toggle.configure(text="▶ 高级选项")
        else:
            self.advanced_frame.grid(
                row=6, column=0, columnspan=2, sticky="ew", padx=0, pady=0
            )
            self.btn_preset.grid(
                row=7, column=0, columnspan=2, sticky="ew", padx=20, pady=(8, 0)
            )
            self.advanced_toggle.configure(text="▼ 高级选项")

    def _apply_deepseek_preset(self):
        """一键填入 DeepSeek 推荐配置"""
        confirm = messagebox.askyesno(
            "DeepSeek 一键预设",
            "将填入 DeepSeek 官方推荐值：\n\n"
            "• API 地址：https://api.deepseek.com/anthropic\n"
            "• 模型：deepseek-v4-pro[1m]\n"
            "• Opus/Sonnet 映射：deepseek-v4-pro[1m]\n"
            "• Haiku/子代理：deepseek-v4-flash\n\n"
            "已有内容将被覆盖，是否继续？",
            parent=self,
        )
        if not confirm:
            return

        if not self.advanced_frame.winfo_viewable():
            self._toggle_advanced()

        preset = {
            "base_url": "https://api.deepseek.com/anthropic",
            "model": "deepseek-v4-pro[1m]",
            "opus_model": "deepseek-v4-pro[1m]",
            "sonnet_model": "deepseek-v4-pro[1m]",
            "haiku_model": "deepseek-v4-flash",
            "subagent_model": "deepseek-v4-flash",
        }
        for key, value in preset.items():
            if key in self.entries:
                entry = self.entries[key]
                if isinstance(entry, ctk.CTkComboBox):
                    if value not in entry.cget("values"):
                        current_vals = list(entry.cget("values"))
                        current_vals.insert(0, value)
                        entry.configure(values=current_vals)
                    entry.set(value)
                else:
                    entry.delete(0, "end")
                    entry.insert(0, value)

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
