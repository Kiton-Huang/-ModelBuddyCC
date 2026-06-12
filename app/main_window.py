"""
ModelBuddyCC — Claude Code 模型配置管理器
主窗口
"""
import os
import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import messagebox, filedialog

from app.constants import EXECUTION_MODES, EXECUTION_MODE_KEYS
from app.theme import COLORS, FONT_FAMILY, _appearance_mode, _sync_colors
from app.models import ModelProfile, LaunchRecord
from app.config import ConfigManager
from app.balance import detect_provider, check_balance
from app.export import _get_conversation_files, _parse_jsonl, _generate_export_html
from app.dashboard import BalanceDashboard
from app.profile_dialog import ProfileDialog
from app.export_dialog import ExportOptionsDialog

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
