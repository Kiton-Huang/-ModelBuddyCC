"""
主题颜色 & 字体配置
"""
import customtkinter as ctk

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
