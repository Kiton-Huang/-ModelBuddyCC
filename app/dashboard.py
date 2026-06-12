"""
余额仪表盘弹窗
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import customtkinter as ctk

from app.theme import COLORS, FONT_FAMILY
from app.models import ModelProfile
from app.balance import detect_provider, check_balance


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
