"""
通知设置标签页 — 闪烁 / 声音 / 邮件配置 UI
各功能区使用卡片样式，系统音效下拉选择 + 独立音量调节
"""
import os
from collections import OrderedDict
from tkinter import messagebox

import customtkinter as ctk

from app.theme import COLORS, FONT_FAMILY
from app.notify_engine import (
    NotifyEngine, SMTP_PRESETS, SMTP_PRESET_KEYS,
    DEFAULT_SOUND_DONE, DEFAULT_SOUND_ATTENTION,
)

# ─── 系统音效预设 ──────────────────────────────────────────

_SOUND_PRESETS = OrderedDict({
    "系统通知":    "Windows Notify.wav",
    "清脆叮":      "ding.wav",
    "叮咚":        "Windows Ding.wav",
    "和弦":       "chimes.wav",
    "和弦2":      "chord.wav",
    "提示音":      "notify.wav",
    "完成":       "tada.wav",
    "气泡":       "Windows Balloon.wav",
    "默认":       "Windows Default.wav",
    "感叹":       "Windows Exclamation.wav",
    "警告":       "Windows Critical Stop.wav",
    "邮件":       "Windows Notify Email.wav",
    "消息":       "Windows Notify Messaging.wav",
})

_WINDOWS_MEDIA = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "Media"
)


def _scan_system_sounds():
    """扫描 Windows Media 目录中实际存在的音效文件

    返回 [(显示名, 完整路径), ...]，按预设顺序。
    """
    options = []
    for name, filename in _SOUND_PRESETS.items():
        full = os.path.join(_WINDOWS_MEDIA, filename)
        if os.path.isfile(full):
            options.append((name, full))
    return options


def _path_to_display(path: str) -> str:
    """将完整路径转换为预设显示名，找不到则返回文件名"""
    basename = os.path.basename(path)
    for name, filename in _SOUND_PRESETS.items():
        if filename == basename:
            return name
    return basename


# ═══════════════════════════════════════════════════════════
# 卡片构建辅助
# ═══════════════════════════════════════════════════════════

class _Card:
    """在 scroll 中创建一个 bg_card 风格的容器帧，内部用 grid 布局"""

    def __init__(self, scroll: ctk.CTkScrollableFrame):
        self.frame = ctk.CTkFrame(
            scroll, corner_radius=10, fg_color=COLORS["bg_card"],
        )
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_columnconfigure(2, weight=0)
        self._row = 0

    def pack(self, **kwargs):
        self.frame.pack(fill="x", padx=0, pady=(0, 10))

    def title(self, text: str, icon: str = ""):
        r = self._row
        self._row += 1
        ctk.CTkLabel(
            self.frame, text=f"{icon} {text}",
            font=(FONT_FAMILY, 14, "bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).grid(row=r, column=0, columnspan=3, sticky="w",
               padx=16, pady=(14, 4))

    def label(self, text: str, **kwargs):
        r = self._row
        self._row += 1
        ctk.CTkLabel(
            self.frame, text=text,
            font=(FONT_FAMILY, kwargs.pop("font_size", 12)),
            text_color=COLORS.get(kwargs.pop("color", "text_secondary"),
                                  COLORS["text_secondary"]),
            anchor="w",
        ).grid(row=r, column=0, columnspan=kwargs.pop("cspan", 3),
               sticky="w", padx=kwargs.pop("padx", (16, 8)),
               pady=kwargs.pop("pady", (3, 2)))

    def hint(self, text: str):
        r = self._row
        self._row += 1
        ctk.CTkLabel(
            self.frame, text=text,
            font=(FONT_FAMILY, 10), text_color=COLORS["text_muted"],
            anchor="w", justify="left",
        ).grid(row=r, column=0, columnspan=3, sticky="w",
               padx=(16, 16), pady=(0, 10))

    def spacer(self, height: int = 6):
        r = self._row
        self._row += 1
        ctk.CTkLabel(self.frame, text="").grid(row=r, column=0, pady=(height, height))


# ═══════════════════════════════════════════════════════════
# 主构建函数
# ═══════════════════════════════════════════════════════════

def build_notify_tab(parent_tab: ctk.CTkFrame, engine: NotifyEngine):
    parent_tab.grid_columnconfigure(0, weight=1)
    parent_tab.grid_rowconfigure(0, weight=1)

    scroll = ctk.CTkScrollableFrame(parent_tab, fg_color="transparent")
    scroll.grid(row=0, column=0, sticky="nsew", padx=12, pady=8)

    s = engine.get_settings()

    # ────────────────────────────────────────────────────
    # 卡片 1：Hook 管理
    # ────────────────────────────────────────────────────
    c1 = _Card(scroll)
    c1.pack()
    c1.title("Claude Code Hook", "🔗")

    def _refresh_hook_status():
        installed = engine.is_hooks_installed()
        s.hooks_installed = installed
        if installed:
            hook_status.configure(
                text="✅ Hook 已安装 — 通知功能生效中",
                text_color=COLORS["success"])
            btn_hook.configure(text="卸载 Hook")
        else:
            hook_status.configure(
                text="⚠ Hook 未安装 — 通知功能不可用",
                text_color=COLORS["warning"])
            btn_hook.configure(text="安装 Hook")

    # 状态行
    row_r = c1._row
    c1._row += 1
    hf = ctk.CTkFrame(c1.frame, fg_color="transparent")
    hf.grid(row=row_r, column=0, columnspan=3, sticky="ew", padx=16, pady=(6, 4))
    hf.grid_columnconfigure(0, weight=1)

    hook_status = ctk.CTkLabel(hf, text="", font=(FONT_FAMILY, 12), anchor="w")
    hook_status.grid(row=0, column=0, sticky="w")

    btn_hook = ctk.CTkButton(
        hf, text="安装 Hook", width=100, height=30,
        font=(FONT_FAMILY, 12, "bold"),
        fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], corner_radius=6,
    )
    btn_hook.grid(row=0, column=1, sticky="e", padx=(8, 0))

    def _toggle_hook():
        if engine.is_hooks_installed():
            if engine.uninstall_hooks():
                _refresh_hook_status()
                messagebox.showinfo("已卸载", "Hook 已从 settings.json 移除。")
            else:
                messagebox.showerror("失败", "卸载 Hook 失败。")
        else:
            if engine.install_hooks():
                _refresh_hook_status()
                messagebox.showinfo("已安装",
                    "Hook 已写入 settings.json。\n下次启动 Claude Code 时生效。")
            else:
                messagebox.showerror("失败", "安装 Hook 失败。")

    btn_hook.configure(command=_toggle_hook)
    c1.hint("Hook 会在 Claude Code 停止回复 / 发起通知时写入事件标记文件，"
            "ModelBuddyCC 监视这些文件并触发通知。安装后对所有 Claude Code 会话生效。")
    _refresh_hook_status()

    # ────────────────────────────────────────────────────
    # 卡片 2：通知开关 + 响应过滤
    # ────────────────────────────────────────────────────
    c2 = _Card(scroll)
    c2.pack()
    c2.title("通知开关", "🎛️")

    # ── 4 个开关 ──
    r = c2._row; c2._row += 1
    row1 = ctk.CTkFrame(c2.frame, fg_color="transparent")
    row1.grid(row=r, column=0, columnspan=3, sticky="ew", padx=16, pady=(4, 2))
    flash_var = ctk.BooleanVar(value=s.flash_enabled)
    ctk.CTkSwitch(row1, text="任务栏闪烁", variable=flash_var, font=(FONT_FAMILY, 12),
        fg_color=COLORS["bg_hover"], progress_color=COLORS["accent"],
        text_color=COLORS["text_primary"], command=lambda: _auto_save()
    ).pack(side="left", padx=(0, 20))

    done_enabled_var = ctk.BooleanVar(value=s.sound_done_enabled)
    ctk.CTkSwitch(row1, text="完成提示音", variable=done_enabled_var, font=(FONT_FAMILY, 12),
        fg_color=COLORS["bg_hover"], progress_color=COLORS["accent"],
        text_color=COLORS["text_primary"], command=lambda: _auto_save()
    ).pack(side="left", padx=(0, 20))

    att_enabled_var = ctk.BooleanVar(value=s.sound_attention_enabled)
    ctk.CTkSwitch(row1, text="权限提示音", variable=att_enabled_var, font=(FONT_FAMILY, 12),
        fg_color=COLORS["bg_hover"], progress_color=COLORS["accent"],
        text_color=COLORS["text_primary"], command=lambda: _auto_save()
    ).pack(side="left", padx=(0, 20))

    email_enabled_var = ctk.BooleanVar(value=s.email_enabled)
    ctk.CTkSwitch(row1, text="邮件通知", variable=email_enabled_var, font=(FONT_FAMILY, 12),
        fg_color=COLORS["bg_hover"], progress_color=COLORS["accent"],
        text_color=COLORS["text_primary"], command=lambda: _auto_save()
    ).pack(side="left")

    c2.spacer(2)

    # ── 响应时间过滤 ──
    resp_enabled_var = ctk.BooleanVar(value=s.response_time_enabled)
    r = c2._row; c2._row += 1
    resp_row = ctk.CTkFrame(c2.frame, fg_color="transparent")
    resp_row.grid(row=r, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 4))
    ctk.CTkSwitch(resp_row, text="响应时间过滤", variable=resp_enabled_var,
        font=(FONT_FAMILY, 12),
        fg_color=COLORS["bg_hover"], progress_color=COLORS["accent"],
        text_color=COLORS["text_primary"], command=lambda: _auto_save(),
    ).pack(side="left")
    ctk.CTkLabel(resp_row, text="  仅当距上次通知超过",
        font=(FONT_FAMILY, 11), text_color=COLORS["text_muted"],
    ).pack(side="left")
    resp_threshold_entry = ctk.CTkEntry(resp_row, font=(FONT_FAMILY, 12),
        width=50, height=26,
        fg_color=COLORS["bg_input"], border_color=COLORS["border"], corner_radius=4,
    )
    resp_threshold_entry.insert(0, str(s.response_time_threshold_sec))
    resp_threshold_entry.pack(side="left")
    ctk.CTkLabel(resp_row, text=" 秒时才通知",
        font=(FONT_FAMILY, 11), text_color=COLORS["text_muted"],
    ).pack(side="left")
    c2.hint("💡 坐在电脑旁快速对话时不打扰，Claude 长时间思考才提醒")

    # ────────────────────────────────────────────────────
    # 卡片 3：声音设置
    # ────────────────────────────────────────────────────
    c3 = _Card(scroll)
    c3.pack()
    c3.title("声音设置", "🔊")

    done_cfg = _SoundConfig(c3, engine,
                             "完成提示音",
                             s.sound_done_path, s.sound_done_volume,
                             done_enabled_var,
                             DEFAULT_SOUND_DONE,
                             on_change=lambda: _auto_save())
    c3.spacer(4)
    att_cfg = _SoundConfig(c3, engine,
                            "权限提示音",
                            s.sound_attention_path, s.sound_attention_volume,
                            att_enabled_var,
                            DEFAULT_SOUND_ATTENTION,
                            on_change=lambda: _auto_save())

    # ────────────────────────────────────────────────────
    # 卡片 4：邮件通知
    # ────────────────────────────────────────────────────
    c4 = _Card(scroll)
    c4.pack()
    c4.title("邮件通知", "📧")

    # SMTP 预设 + 服务器 + 端口
    r = c4._row; c4._row += 1
    preset_var = ctk.StringVar(value=s.email_preset)
    preset_combo = ctk.CTkComboBox(c4.frame, values=SMTP_PRESET_KEYS, variable=preset_var,
        font=(FONT_FAMILY, 12), width=150, height=30,
        fg_color=COLORS["bg_input"], border_color=COLORS["border"],
        button_color=COLORS["bg_hover"], button_hover_color=COLORS["accent"],
        corner_radius=6, dropdown_font=(FONT_FAMILY, 12),
    )
    preset_combo.grid(row=r, column=0, sticky="w", padx=(16, 4))

    smtp_server_entry = ctk.CTkEntry(c4.frame, font=(FONT_FAMILY, 12), height=30,
        fg_color=COLORS["bg_input"], border_color=COLORS["border"], corner_radius=6,
        placeholder_text="SMTP 服务器",
    )
    smtp_server_entry.insert(0, s.email_smtp_server)
    smtp_server_entry.grid(row=r, column=1, sticky="ew", padx=(0, 4))

    smtp_port_entry = ctk.CTkEntry(c4.frame, font=(FONT_FAMILY, 12), height=30, width=56,
        fg_color=COLORS["bg_input"], border_color=COLORS["border"], corner_radius=6,
        placeholder_text="端口",
    )
    smtp_port_entry.insert(0, str(s.email_smtp_port))
    smtp_port_entry.grid(row=r, column=2, sticky="w", padx=(0, 16))

    # SSL + 发件人
    r = c4._row; c4._row += 1
    ssl_var = ctk.BooleanVar(value=s.email_use_ssl)
    ctk.CTkCheckBox(c4.frame, text="SSL", variable=ssl_var, font=(FONT_FAMILY, 12),
        fg_color=COLORS["accent"], text_color=COLORS["text_secondary"],
        border_color=COLORS["border"], checkmark_color=COLORS["text_primary"],
    ).grid(row=r, column=0, sticky="w", padx=(16, 0))

    sender_entry = ctk.CTkEntry(c4.frame, font=(FONT_FAMILY, 12), height=30,
        fg_color=COLORS["bg_input"], border_color=COLORS["border"], corner_radius=6,
        placeholder_text="发件邮箱",
    )
    sender_entry.insert(0, s.email_sender)
    sender_entry.grid(row=r, column=1, columnspan=2, sticky="ew", padx=(0, 16))

    # 授权码 + 收件人
    r = c4._row; c4._row += 1
    password_entry = ctk.CTkEntry(c4.frame, font=(FONT_FAMILY, 12), height=30,
        fg_color=COLORS["bg_input"], border_color=COLORS["border"], corner_radius=6,
        show="•", placeholder_text="授权码",
    )
    password_entry.insert(0, s.email_password)
    password_entry.grid(row=r, column=0, sticky="ew", padx=(16, 4))

    recipient_entry = ctk.CTkEntry(c4.frame, font=(FONT_FAMILY, 12), height=30,
        fg_color=COLORS["bg_input"], border_color=COLORS["border"], corner_radius=6,
        placeholder_text="收件邮箱",
    )
    recipient_entry.insert(0, s.email_recipient)
    recipient_entry.grid(row=r, column=1, columnspan=2, sticky="ew", padx=(0, 16))

    # 提示 + 测试
    r = c4._row; c4._row += 1
    ctk.CTkLabel(c4.frame, text="💡 主流邮箱需使用「授权码」而非登录密码",
        font=(FONT_FAMILY, 10), text_color=COLORS["text_muted"], anchor="w",
    ).grid(row=r, column=0, columnspan=3, sticky="w", padx=16, pady=(2, 4))

    r = c4._row; c4._row += 1
    email_row = ctk.CTkFrame(c4.frame, fg_color="transparent")
    email_row.grid(row=r, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 6))
    email_row.grid_columnconfigure(0, weight=1)
    email_status = ctk.CTkLabel(email_row, text="", font=(FONT_FAMILY, 11),
                                 text_color=COLORS["text_muted"], anchor="w")
    email_status.grid(row=0, column=0, sticky="w")
    btn_test_email = ctk.CTkButton(email_row, text="发送测试邮件", width=110, height=28,
        font=(FONT_FAMILY, 11),
        fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], corner_radius=6,
    )
    btn_test_email.grid(row=0, column=1, sticky="e")

    def _on_preset_changed(val: str):
        preset = SMTP_PRESETS.get(val, {})
        smtp_server_entry.delete(0, "end")
        smtp_server_entry.insert(0, preset.get("server", ""))
        smtp_port_entry.delete(0, "end")
        smtp_port_entry.insert(0, str(preset.get("port", 587)))
        ssl_var.set(preset.get("use_ssl", False))
    preset_combo.configure(command=_on_preset_changed)

    def _test_email():
        server = smtp_server_entry.get().strip()
        try: port = int(smtp_port_entry.get().strip())
        except ValueError:
            email_status.configure(text="端口无效", text_color=COLORS["danger"]); return
        use_ssl = ssl_var.get(); sender = sender_entry.get().strip()
        password = password_entry.get().strip(); recipient = recipient_entry.get().strip()
        if not all([server, port, sender, password, recipient]):
            email_status.configure(text="信息不完整", text_color=COLORS["danger"]); return
        email_status.configure(text="发送中...", text_color=COLORS["text_muted"])
        btn_test_email.configure(state="disabled", text="发送中...")
        def cb(success, msg):
            btn_test_email.configure(state="normal", text="发送测试邮件")
            email_status.configure(text=msg, text_color=COLORS["success"] if success else COLORS["danger"])
        engine.send_test_email(server, port, use_ssl, sender, password, recipient, cb)
    btn_test_email.configure(command=_test_email)

    # ────────────────────────────────────────────────────
    # 底部：保存 / 重置
    # ────────────────────────────────────────────────────
    bottom = ctk.CTkFrame(scroll, fg_color="transparent")
    bottom.pack(fill="x", pady=(4, 20))

    save_hint_label = ctk.CTkLabel(bottom, text="", font=(FONT_FAMILY, 11),
                                    text_color=COLORS["success"])
    save_hint_label.pack(side="left", padx=8)

    ctk.CTkButton(
        bottom, text="恢复默认", width=100, height=34,
        font=(FONT_FAMILY, 12),
        fg_color="transparent", text_color=COLORS["text_muted"],
        hover_color=COLORS["bg_hover"],
        border_width=1, border_color=COLORS["border"], corner_radius=6,
        command=lambda: _reset_defaults(),
    ).pack(side="left", padx=6)

    ctk.CTkButton(
        bottom, text="💾 保存设置", width=120, height=34,
        font=(FONT_FAMILY, 12, "bold"),
        fg_color=COLORS["success"], hover_color=COLORS["success_hover"], corner_radius=6,
        command=lambda: _save(),
    ).pack(side="left", padx=6)

    # ── 收集 & 保存 ──
    def _collect():
        s.flash_enabled = flash_var.get()
        s.sound_done_path = done_cfg.get_path()
        s.sound_done_volume = done_cfg.get_volume()
        s.sound_done_enabled = done_enabled_var.get()
        s.sound_attention_path = att_cfg.get_path()
        s.sound_attention_volume = att_cfg.get_volume()
        s.sound_attention_enabled = att_enabled_var.get()
        s.response_time_enabled = resp_enabled_var.get()
        try:
            s.response_time_threshold_sec = int(resp_threshold_entry.get().strip())
        except ValueError:
            s.response_time_threshold_sec = 60
        s.email_enabled = email_enabled_var.get()
        s.email_preset = preset_var.get()
        s.email_smtp_server = smtp_server_entry.get().strip()
        try:
            s.email_smtp_port = int(smtp_port_entry.get().strip())
        except ValueError:
            s.email_smtp_port = 587
        s.email_use_ssl = ssl_var.get()
        s.email_sender = sender_entry.get().strip()
        s.email_password = password_entry.get().strip()
        s.email_recipient = recipient_entry.get().strip()

    def _auto_save():
        _collect()
        engine.save_settings()

    def _save():
        _auto_save()
        save_hint_label.configure(text="✓ 已保存")
        scroll.after(2500, lambda: save_hint_label.configure(text=""))

    def _reset_defaults():
        if not messagebox.askyesno("恢复默认", "确定要将所有通知设置恢复为默认值吗？"):
            return
        flash_var.set(True)
        done_enabled_var.set(True)
        att_enabled_var.set(True)
        done_cfg.reset()
        att_cfg.reset()
        resp_enabled_var.set(False)
        resp_threshold_entry.delete(0, "end")
        resp_threshold_entry.insert(0, "60")
        email_enabled_var.set(False)
        preset_var.set("自定义")
        smtp_server_entry.delete(0, "end")
        smtp_port_entry.delete(0, "end")
        smtp_port_entry.insert(0, "587")
        ssl_var.set(False)
        sender_entry.delete(0, "end")
        password_entry.delete(0, "end")
        recipient_entry.delete(0, "end")
        _collect()
        engine.save_settings()
        save_hint_label.configure(text="✓ 已恢复默认")
        scroll.after(2500, lambda: save_hint_label.configure(text=""))


# ═══════════════════════════════════════════════════════════
# 声音配置组件
# ═══════════════════════════════════════════════════════════

class _SoundConfig:
    """声音配置：系统音效下拉选择、试听、音量"""

    def __init__(self, card: _Card, engine: NotifyEngine,
                 name: str,
                 init_path: str, init_vol: int,
                 enabled_var: ctk.BooleanVar,
                 default_path: str,
                 on_change=None):
        self._engine = engine
        self._name = name
        self._enabled_var = enabled_var
        self._default_path = default_path
        self._on_change = on_change

        # 扫描可用系统音效
        self._sound_options = _scan_system_sounds()  # [(显示名, 路径), ...]
        if not self._sound_options:
            self._sound_options = [("⚠ 无可用音效", "")]

        # 根据 init_path 确定初始选中
        init_display = _path_to_display(init_path)
        option_names = [n for n, _ in self._sound_options]
        if init_display not in option_names:
            # 旧的自定义路径 → 补充为额外选项（但不保证文件存在）
            if init_path and os.path.isfile(init_path):
                option_names.insert(0, init_display)
                self._sound_options.insert(0, (init_display, init_path))
            init_display = _path_to_display(default_path)
        self._path = self._lookup_path(init_display)

        # 标题
        r = card._row; card._row += 1
        ctk.CTkLabel(card.frame, text=f"🎵 {name}",
            font=(FONT_FAMILY, 13, "bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).grid(row=r, column=0, columnspan=3, sticky="w", padx=16, pady=(8, 4))

        # 音效选择行：标签 + 下拉框
        r = card._row; card._row += 1
        ctk.CTkLabel(card.frame, text="音效选择",
            font=(FONT_FAMILY, 12), text_color=COLORS["text_secondary"], anchor="w",
        ).grid(row=r, column=0, sticky="w", padx=(24, 8), pady=(2, 2))

        self._combo_var = ctk.StringVar(value=init_display)
        self._combo = ctk.CTkComboBox(
            card.frame, values=option_names, variable=self._combo_var,
            font=(FONT_FAMILY, 12), height=30,
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            button_color=COLORS["bg_hover"], button_hover_color=COLORS["accent"],
            corner_radius=6, dropdown_font=(FONT_FAMILY, 12),
            command=self._on_sound_changed,
        )
        self._combo.grid(row=r, column=1, columnspan=2, sticky="ew",
                         padx=(0, 16), pady=(2, 2))

        # 试听 + 恢复默认 + 音量标签
        r = card._row; card._row += 1
        self._btn_test = ctk.CTkButton(card.frame, text="▶ 试听", width=60, height=28,
            font=(FONT_FAMILY, 11),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], corner_radius=6,
            command=self._on_test,
        )
        self._btn_test.grid(row=r, column=0, sticky="w", padx=(24, 8), pady=(2, 2))

        self._btn_reset = ctk.CTkButton(card.frame, text="恢复默认", width=70, height=28,
            font=(FONT_FAMILY, 11),
            fg_color="transparent", text_color=COLORS["text_muted"],
            hover_color=COLORS["bg_hover"],
            border_width=1, border_color=COLORS["border"], corner_radius=6,
            command=self._on_reset,
        )
        self._btn_reset.grid(row=r, column=1, sticky="w", padx=(0, 8), pady=(2, 2))

        self._vol_label = ctk.CTkLabel(card.frame, text=f"{init_vol}%",
            font=(FONT_FAMILY, 11, "bold"),
            text_color=COLORS["text_primary"], width=40,
        )
        self._vol_label.grid(row=r, column=2, sticky="e", padx=(0, 16), pady=(2, 2))

        # 音量滑块
        r = card._row; card._row += 1
        self._vol_var = ctk.IntVar(value=init_vol)
        self._vol_slider = ctk.CTkSlider(card.frame, from_=0, to=100, number_of_steps=100,
            variable=self._vol_var, width=250,
            fg_color=COLORS["bg_hover"], progress_color=COLORS["accent"],
            button_color=COLORS["accent_light"], button_hover_color=COLORS["accent"],
        )
        self._vol_slider.set(init_vol)
        self._vol_slider.grid(row=r, column=0, columnspan=3, sticky="ew",
                               padx=(24, 16), pady=(0, 8))

        def _on_vol(val):
            self._vol_label.configure(text=f"{int(float(val))}%")
        self._vol_slider.configure(command=_on_vol)

    # ── 查找函数 ──────────────────────────────────────────

    def _lookup_path(self, display: str) -> str:
        for name, path in self._sound_options:
            if name == display:
                return path
        return ""

    def _lookup_display(self, path: str) -> str:
        for name, p in self._sound_options:
            if p == path:
                return name
        return _path_to_display(path)

    # ── 回调 ──────────────────────────────────────────────

    def _on_sound_changed(self, display_name):
        self._path = self._lookup_path(display_name)
        if self._on_change:
            self._on_change()

    def _on_test(self):
        path = self.get_path()
        if path and os.path.isfile(path):
            self._engine.play_sound(path=path, volume=self.get_volume())
        else:
            messagebox.showwarning("提示", "当前音效文件不存在，请重新选择。")

    def _on_reset(self):
        default_display = _path_to_display(self._default_path)
        # 确保默认音效在下拉列表中
        if default_display not in [n for n, _ in self._sound_options]:
            default_display = self._sound_options[0][0] if self._sound_options else ""
        self._combo_var.set(default_display)
        self._on_sound_changed(default_display)

    # ── 公共接口 ──────────────────────────────────────────

    def get_path(self) -> str: return self._path
    def get_volume(self) -> int: return int(self._vol_var.get())

    def reset(self):
        default_display = _path_to_display(self._default_path)
        if default_display not in [n for n, _ in self._sound_options]:
            default_display = self._sound_options[0][0] if self._sound_options else ""
        self._combo_var.set(default_display)
        self._on_sound_changed(default_display)
        self._vol_slider.set(80)
        self._vol_label.configure(text="80%")
