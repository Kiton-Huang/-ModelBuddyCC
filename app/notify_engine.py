"""
通知引擎 — 任务栏闪烁 + 声音播放 + 邮件发送 + Hook 管理 + 事件监视

通过 Claude Code 的 Stop / Notification hooks 写标记文件，
后台线程轮询检测事件并触发通知。

默认音效使用 Windows 系统声音文件，通过 MCI 播放并支持音量调节。
"""
import os
import re
import io
import json
import struct
import wave
import winsound
import smtplib
import threading
import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass, asdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime

from app.constants import (
    CLAUDE_SETTINGS, BACKUP_DIR,
    NOTIFY_SETTINGS_FILE, NOTIFY_EVENTS_DIR,
    TRANSCRIPTS_DIR,
)

# ─── SMTP 预设 ─────────────────────────────────────────────
SMTP_PRESETS = {
    "自定义":         {"server": "",   "port": 587, "use_ssl": False},
    "QQ邮箱":         {"server": "smtp.qq.com",       "port": 587, "use_ssl": False},
    "QQ邮箱(SSL)":    {"server": "smtp.qq.com",       "port": 465, "use_ssl": True},
    "163邮箱":        {"server": "smtp.163.com",      "port": 465, "use_ssl": True},
    "163邮箱(TLS)":   {"server": "smtp.163.com",      "port": 587, "use_ssl": False},
    "126邮箱":        {"server": "smtp.126.com",      "port": 465, "use_ssl": True},
    "Gmail":          {"server": "smtp.gmail.com",    "port": 587, "use_ssl": False},
    "Gmail(SSL)":     {"server": "smtp.gmail.com",    "port": 465, "use_ssl": True},
    "Outlook":        {"server": "smtp-mail.outlook.com", "port": 587, "use_ssl": False},
    "新浪邮箱":       {"server": "smtp.sina.com",     "port": 465, "use_ssl": True},
    "搜狐邮箱":       {"server": "smtp.sohu.com",     "port": 465, "use_ssl": True},
    "阿里企业邮箱":   {"server": "smtp.qiye.aliyun.com", "port": 465, "use_ssl": True},
    "139邮箱":        {"server": "smtp.139.com",      "port": 465, "use_ssl": True},
    "Yeah邮箱":       {"server": "smtp.yeah.net",     "port": 465, "use_ssl": True},
}

SMTP_PRESET_KEYS = list(SMTP_PRESETS.keys())

# ─── Windows 系统声音文件路径 ──────────────────────────────
_WINDOWS_MEDIA_DIR = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "Media"
)
DEFAULT_SOUND_DONE = os.path.join(_WINDOWS_MEDIA_DIR, "Windows Notify.wav")
DEFAULT_SOUND_ATTENTION = os.path.join(_WINDOWS_MEDIA_DIR, "Windows Exclamation.wav")


# ─── 设置数据模型 ──────────────────────────────────────────
@dataclass
class NotifySettings:
    """通知设置数据结构"""
    flash_enabled: bool = True
    sound_done_enabled: bool = True
    sound_done_path: str = ""       # 完成音效文件路径（from_dict 补默认值）
    sound_done_volume: int = 80     # 0-100
    sound_attention_enabled: bool = True
    sound_attention_path: str = ""  # 注意音效文件路径（from_dict 补默认值）
    sound_attention_volume: int = 80
    response_time_enabled: bool = False
    response_time_threshold_sec: int = 60  # 默认 1 分钟
    startup_enabled: bool = False
    email_enabled: bool = False
    email_preset: str = "自定义"
    email_smtp_server: str = ""
    email_smtp_port: int = 587
    email_use_ssl: bool = False
    email_sender: str = ""
    email_password: str = ""        # base64 简单编码存储
    email_recipient: str = ""
    hooks_installed: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        if d.get("email_password"):
            import base64
            d["email_password"] = base64.b64encode(
                d["email_password"].encode("utf-8")
            ).decode("utf-8")
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "NotifySettings":
        defaults = {k: v for k, v in cls().__dict__.items()}
        merged = {k: d.get(k, defaults[k]) for k in defaults}
        if merged.get("email_password"):
            try:
                import base64
                merged["email_password"] = base64.b64decode(
                    merged["email_password"].encode("utf-8")
                ).decode("utf-8")
            except Exception:
                pass
        # 向后兼容：空路径或已删除文件 → 默认系统音效
        if not merged.get("sound_done_path") or not os.path.isfile(
            merged["sound_done_path"]
        ):
            merged["sound_done_path"] = DEFAULT_SOUND_DONE
        if not merged.get("sound_attention_path") or not os.path.isfile(
            merged["sound_attention_path"]
        ):
            merged["sound_attention_path"] = DEFAULT_SOUND_ATTENTION
        return cls(**merged)


# ─── 通知引擎 ──────────────────────────────────────────────
class NotifyEngine:
    """管理所有通知功能：闪烁、声音、邮件、Hook、监视器"""

    # ── FlashWindowEx 常量 ─────────────────────────────────
    FLASHW_STOP = 0
    FLASHW_CAPTION = 1
    FLASHW_TRAY = 2
    FLASHW_ALL = 3
    FLASHW_TIMER = 4
    FLASHW_TIMERNOFG = 12

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("hwnd", wintypes.HWND),
            ("dwFlags", wintypes.DWORD),
            ("uCount", wintypes.UINT),
            ("dwTimeout", wintypes.DWORD),
        ]

    def __init__(self, root):
        """
        Args:
            root: tkinter.Tk / CTk 根窗口（需要 .winfo_id() 获取 HWND）
        """
        self._root = root
        self._settings: NotifySettings = NotifySettings()
        self._watcher_running = False
        self._watcher_thread = None
        self._lock = threading.Lock()

        # 防重复通知定时器 ID
        self._stop_timer_id = None
        self._attention_timer_id = None
        self._STOP_DEBOUNCE_MS = 2000
        self._ATTENTION_DEBOUNCE_MS = 1000

        # 响应时间过滤
        self._last_notify_at: float = 0.0

        # MCI 声音播放锁
        self._sound_lock = threading.Lock()
        self._sound_data = None  # 播放中的 WAV 数据引用

        # 确保事件标记目录存在
        NOTIFY_EVENTS_DIR.mkdir(parents=True, exist_ok=True)

        # 加载设置
        self.load_settings()

    # ── 设置存取 ───────────────────────────────────────────
    def load_settings(self):
        if NOTIFY_SETTINGS_FILE.exists():
            try:
                raw = json.loads(NOTIFY_SETTINGS_FILE.read_text(encoding="utf-8"))
                self._settings = NotifySettings.from_dict(raw)
            except Exception:
                self._settings = NotifySettings()
        # 确保路径不为空（新实例或旧设置迁移）
        if not self._settings.sound_done_path:
            self._settings.sound_done_path = DEFAULT_SOUND_DONE
        if not self._settings.sound_attention_path:
            self._settings.sound_attention_path = DEFAULT_SOUND_ATTENTION

    def save_settings(self):
        with self._lock:
            NOTIFY_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            NOTIFY_SETTINGS_FILE.write_text(
                json.dumps(self._settings.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _debug(self, msg: str):
        """调试日志（生产环境禁用，取消注释即可启用）"""
        # import os
        # ts = datetime.now().strftime("%H:%M:%S")
        # with open(NOTIFY_EVENTS_DIR / "debug.log", "a", encoding="utf-8") as f:
        #     f.write(f"[{ts}] {msg}\n")
        pass

    def get_settings(self) -> NotifySettings:
        return self._settings

    # ── 任务栏闪烁 ─────────────────────────────────────────
    def flash_taskbar(self, count: int = 0):
        """闪烁任务栏图标。count=0 持续闪烁直到窗口获得焦点"""
        try:
            # 用 FindWindowW 找真正的顶层窗口 HWND
            # winfo_id() 在 CustomTkinter 中返回的 hwnd 与任务栏不对应
            hwnd = ctypes.windll.user32.FindWindowW(None, self._root.title())
            if not hwnd:
                hwnd = self._root.winfo_id()  # 兜底
            if not hwnd:
                self._debug("flash: hwnd is 0")
                return False
            self._debug(f"flash: hwnd={hwnd}")

            info = self.FLASHWINFO()
            info.cbSize = ctypes.sizeof(info)
            info.hwnd = hwnd
            if count > 0:
                info.dwFlags = self.FLASHW_ALL | self.FLASHW_TIMER
                info.uCount = count
            else:
                info.dwFlags = self.FLASHW_ALL | self.FLASHW_TIMERNOFG
                info.uCount = 0
            info.dwTimeout = 0
            ret = ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
            self._debug(f"flash: FlashWindowEx returned {ret}")
            return bool(ret)
        except Exception as e:
            self._debug(f"flash exception: {e}")
            return False

    # ── 声音播放 ───────────────────────────────────────────
    def play_sound(self, path: str = "", volume: int = 80):
        """
        播放声音（后台线程，非阻塞）。

        通过 MCI 播放指定的 WAV 文件，支持音量调节。
        path 为空或文件不存在时静默跳过。
        """
        if path and os.path.isfile(path):
            self._play_wav(path, volume)

    def _play_wav(self, path: str, volume: int):
        """播放 WAV 文件并调节音量（wave 采样缩放 + winsound，后台线程）"""
        def _play():
            acquired = self._sound_lock.acquire(blocking=False)
            if not acquired:
                return

            try:
                with wave.open(path, "rb") as wav:
                    params = wav.getparams()
                    raw = wav.readframes(params.nframes)

                factor = max(0, min(100, volume)) / 100.0

                if params.sampwidth == 2:
                    samples = struct.unpack(
                        f"<{params.nframes * params.nchannels}h", raw
                    )
                    adjusted = [
                        max(-32768, min(32767, int(s * factor))) for s in samples
                    ]
                    adjusted_frames = struct.pack(
                        f"<{len(adjusted)}h", *adjusted
                    )
                elif params.sampwidth == 1:
                    adjusted_frames = bytes(
                        max(0, min(255, int(128 + (b - 128) * factor)))
                        for b in raw
                    )
                else:
                    adjusted_frames = raw  # 不支持的位深，原样播放

                buf = io.BytesIO()
                with wave.open(buf, "wb") as wav_out:
                    wav_out.setparams(params)
                    wav_out.writeframes(adjusted_frames)

                self._sound_data = buf.getvalue()  # 保持引用防 GC
                winsound.PlaySound(
                    self._sound_data,
                    winsound.SND_MEMORY | winsound.SND_NODEFAULT,
                )
            except Exception:
                pass
            finally:
                self._sound_lock.release()

        threading.Thread(target=_play, daemon=True).start()

    def stop_sound(self):
        """立即停止当前声音"""
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        try:
            self._sound_lock.release()
        except Exception:
            pass

    # ── 对话摘要提取 ────────────────────────────────────────
    def _get_conversation_summary(self) -> str:
        """从最近对话中提取最后一条助手消息的摘要"""
        try:
            if not TRANSCRIPTS_DIR.exists():
                return ""
            # 收集所有项目下的 JSONL，按文件修改时间找最新的
            all_files = []
            for d in TRANSCRIPTS_DIR.iterdir():
                if d.is_dir():
                    all_files.extend(d.glob("*.jsonl"))
            if not all_files:
                return ""
            latest_file = max(all_files, key=lambda f: f.stat().st_mtime)
            # 读最后一条 user 和最后一条 assistant 消息
            last_user_text = ""
            last_assistant_text = ""
            last_ts = ""
            with open(latest_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        msg = json.loads(line.strip())
                        content = msg.get("message", {}).get("content", "")
                        text = ""
                        if isinstance(content, list):
                            texts = []
                            for b in content:
                                if isinstance(b, dict) and b.get("type") == "text":
                                    texts.append(b.get("text", ""))
                            text = "\n".join(texts)
                        elif isinstance(content, str):
                            text = content

                        if msg.get("type") == "user":
                            last_user_text = text
                        elif msg.get("type") == "assistant":
                            last_assistant_text = text
                            last_ts = msg.get("timestamp", "")
                    except json.JSONDecodeError:
                        continue

            if not last_assistant_text.strip():
                return ""

            # 去掉代码块和表格
            user_text = re.sub(r'```[\s\S]*?```', '', last_user_text).strip()
            asst_text = re.sub(r'```[\s\S]*?```', '', last_assistant_text)
            asst_text = re.sub(r'^\|.*\|$', '', asst_text, flags=re.MULTILINE)
            asst_text = re.sub(r'\n{3,}', '\n\n', asst_text).strip()

            # 限制单段长度
            def _trim(s, n=120):
                if len(s) > n:
                    return s[:n//2] + "..." + s[-n//2:]
                return s

            user_text = _trim(user_text)
            asst_text = _trim(asst_text, 250)

            # 尝试计算耗时
            duration = ""
            if last_ts:
                try:
                    dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    file_mtime = datetime.fromtimestamp(latest_file.stat().st_mtime)
                    secs = (file_mtime - dt.replace(tzinfo=None)).total_seconds()
                    if 1 < secs < 3600:
                        if secs < 60:
                            duration = f"⏱ Cooked for {int(secs)}s"
                        else:
                            m, s = divmod(int(secs), 60)
                            duration = f"⏱ Cooked for {m}m {s}s"
                except Exception:
                    pass

            # 组装输出
            parts = []
            if user_text:
                parts.append(f'需求："{user_text}"')
                parts.append("")
            parts.append(f"结果：[{asst_text}]" if asst_text else "结果：[]")

            return "\n".join(parts)
        except Exception:
            return ""

    # ── 邮件发送 ────────────────────────────────────────────
    def send_email(self, event_type: str, summary: str = "", callback=None):
        """
        在后台线程发送通知邮件
        callback(status: str) 在主线程被调用
        """
        s = self._settings
        if not s.email_enabled:
            if callback:
                callback("邮件通知未开启")
            return
        if not s.email_smtp_server or not s.email_sender or not s.email_recipient:
            if callback:
                callback("SMTP 信息不完整")
            return

        def _send():
            try:
                msg = MIMEMultipart()
                msg["From"] = s.email_sender
                msg["To"] = s.email_recipient

                if event_type == "stop":
                    msg["Subject"] = "[ModelBuddyCC] Claude Code 任务完成通知"
                    body = "Claude Code 已完成当前任务。\n\n"
                    if summary:
                        body += f"{summary}\n\n"
                    body += (
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"-- ModelBuddyCC 自动发送"
                    )
                else:
                    msg["Subject"] = "[ModelBuddyCC] Claude Code 需要你的注意"
                    body = (
                        f"Claude Code 正在等待你的确认/回复。\n\n"
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"-- ModelBuddyCC 自动发送"
                    )
                msg.attach(MIMEText(body, "plain", "utf-8"))

                if s.email_use_ssl:
                    server = smtplib.SMTP_SSL(s.email_smtp_server, s.email_smtp_port, timeout=15)
                else:
                    server = smtplib.SMTP(s.email_smtp_server, s.email_smtp_port, timeout=15)
                    server.ehlo()
                    server.starttls()
                    server.ehlo()

                server.login(s.email_sender, s.email_password)
                server.sendmail(s.email_sender, [s.email_recipient], msg.as_string())
                server.quit()

                if callback:
                    self._root.after(0, lambda: callback("邮件发送成功"))
            except smtplib.SMTPAuthenticationError:
                if callback:
                    self._root.after(0, lambda: callback("认证失败，请检查邮箱账号和授权码"))
            except Exception as e:
                err_msg = str(e)
                if callback:
                    self._root.after(0, lambda em=err_msg: callback(f"发送失败: {em}"))

        threading.Thread(target=_send, daemon=True).start()

    def send_test_email(self, smtp_server, smtp_port, use_ssl,
                        sender, password, recipient, callback=None):
        """发送测试邮件（使用临时参数，不读已保存设置）"""
        def _send():
            try:
                msg = MIMEMultipart()
                msg["From"] = sender
                msg["To"] = recipient
                msg["Subject"] = "[ModelBuddyCC] 测试邮件"
                body = (
                    f"这是一封来自 ModelBuddyCC 的测试邮件。\n\n"
                    f"如果你收到了此邮件，说明 SMTP 配置正确。\n\n"
                    f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                msg.attach(MIMEText(body, "plain", "utf-8"))

                if use_ssl:
                    server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
                else:
                    server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
                    server.ehlo()
                    server.starttls()
                    server.ehlo()

                server.login(sender, password)
                server.sendmail(sender, [recipient], msg.as_string())
                server.quit()

                if callback:
                    self._root.after(0, lambda: callback(True, "测试邮件发送成功"))
            except smtplib.SMTPAuthenticationError:
                if callback:
                    self._root.after(0, lambda: callback(False, "认证失败：请检查邮箱账号和授权码（非邮箱登录密码）"))
            except smtplib.SMTPConnectError:
                if callback:
                    self._root.after(0, lambda: callback(False, "连接失败：无法连接到 SMTP 服务器，请检查地址和端口"))
            except Exception as e:
                err = str(e)
                if callback:
                    self._root.after(0, lambda em=err: callback(False, f"发送失败: {em}"))

        threading.Thread(target=_send, daemon=True).start()

    # ── Hook 管理 ──────────────────────────────────────────
    @property
    def _stop_flag(self) -> Path:
        return NOTIFY_EVENTS_DIR / "stop.flag"

    @property
    def _attention_flag(self) -> Path:
        return NOTIFY_EVENTS_DIR / "attention.flag"

    def install_hooks(self) -> bool:
        """在 ~/.claude/settings.json 中安装 Stop + Notification hooks"""
        try:
            data = {}
            if CLAUDE_SETTINGS.exists():
                data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
            # 备份
            import shutil
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(str(CLAUDE_SETTINGS), str(BACKUP_DIR / f"settings.json.{ts}.bak"))

            # 使用正斜杠避免转义地狱，路径无空格无需引号
            events_fwd = str(NOTIFY_EVENTS_DIR).replace("\\", "/")

            stop_cmd = (
                f'cmd /c "(echo %date% %time%)>'
                f'{events_fwd}/stop.flag"'
            )
            attention_cmd = (
                f'cmd /c "(echo %date% %time%)>'
                f'{events_fwd}/attention.flag"'
            )

            if "hooks" not in data:
                data["hooks"] = {}

            data["hooks"]["Stop"] = [{
                "matcher": "",
                "hooks": [{"type": "command", "command": stop_cmd}],
            }]
            data["hooks"]["Notification"] = [{
                "matcher": "",
                "hooks": [{"type": "command", "command": attention_cmd}],
            }]

            CLAUDE_SETTINGS.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._settings.hooks_installed = True
            self.save_settings()
            return True
        except Exception as e:
            print(f"安装 Hook 失败: {e}")
            return False

    def uninstall_hooks(self) -> bool:
        """从 settings.json 移除 ModelBuddyCC 的 hooks"""
        try:
            if not CLAUDE_SETTINGS.exists():
                self._settings.hooks_installed = False
                self.save_settings()
                return True

            data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
            hooks = data.get("hooks", {})

            for key in ("Stop", "Notification"):
                if key in hooks:
                    hooks[key] = [
                        h for h in hooks[key]
                        if "modelbuddy_events" not in json.dumps(h)
                    ]
                    if not hooks[key]:
                        del hooks[key]

            if not hooks:
                data.pop("hooks", None)

            CLAUDE_SETTINGS.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._settings.hooks_installed = False
            self.save_settings()
            return True
        except Exception as e:
            print(f"卸载 Hook 失败: {e}")
            return False

    def is_hooks_installed(self) -> bool:
        """检测当前 settings.json 是否已安装 hooks"""
        try:
            if not CLAUDE_SETTINGS.exists():
                return False
            data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
            hooks = data.get("hooks", {})
            for key in ("Stop", "Notification"):
                for entry in hooks.get(key, []):
                    if "modelbuddy_events" in json.dumps(entry):
                        return True
            return False
        except Exception:
            return False

    # ── 开机自启动 ──────────────────────────────────────────
    @staticmethod
    def _get_startup_cmd() -> str:
        """返回自启动命令行：打包后用 exe 路径，源码用 pythonw"""
        import sys
        if getattr(sys, 'frozen', False):
            # PyInstaller 打包
            return f'"{sys.executable}"'
        else:
            # 源码运行 — 必须用完整路径，开机启动时 PATH 可能未加载
            main_py = str(Path(sys.argv[0]).resolve())
            # pythonw.exe 与 python.exe 在同一目录
            pythonw_path = Path(sys.executable).with_name("pythonw.exe")
            return f'"{pythonw_path}" "{main_py}"'

    def install_startup(self) -> bool:
        """添加到 Windows 开机启动（注册表 Run 键）"""
        try:
            import winreg
            cmd = self._get_startup_cmd()
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, "ModelBuddyCC", 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            self._settings.startup_enabled = True
            self.save_settings()
            return True
        except Exception as e:
            print(f"安装自启动失败: {e}")
            return False

    def uninstall_startup(self) -> bool:
        """从 Windows 开机启动中移除"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            winreg.DeleteValue(key, "ModelBuddyCC")
            winreg.CloseKey(key)
            self._settings.startup_enabled = False
            self.save_settings()
            return True
        except FileNotFoundError:
            self._settings.startup_enabled = False
            self.save_settings()
            return True
        except Exception as e:
            print(f"卸载自启动失败: {e}")
            return False

    def is_startup_installed(self) -> bool:
        """检查是否已注册开机启动"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ,
            )
            try:
                winreg.QueryValueEx(key, "ModelBuddyCC")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except Exception:
            return False

    # ── 事件监视器 ─────────────────────────────────────────
    def start_watching(self):
        """启动后台线程监视标记文件"""
        if self._watcher_running:
            return
        self._watcher_running = True
        self._watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watcher_thread.start()

    def stop_watching(self):
        self._watcher_running = False
        for p in (self._stop_flag, self._attention_flag):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    def _watch_loop(self):
        """后台轮询：检测标志文件并触发通知"""
        while self._watcher_running:
            try:
                processed = False

                if self._stop_flag.exists():
                    self._stop_flag.unlink()
                    self._debug("stop flag detected -> scheduling _on_event(stop)")
                    self._root.after(0, lambda: self._on_event("stop"))
                    processed = True

                if self._attention_flag.exists():
                    self._attention_flag.unlink()
                    self._debug("attention flag detected -> scheduling _on_event(attention)")
                    self._root.after(0, lambda: self._on_event("attention"))
                    processed = True

            except Exception as e:
                self._debug(f"watch error: {e}")

            time.sleep(1.0 if not processed else 0.3)

    def _on_event(self, event_type: str):
        """主线程回调：处理通知事件（含防抖）"""
        self._debug(f"_on_event({event_type}) - starting debounce")
        if event_type == "stop":
            if self._stop_timer_id is not None:
                self._root.after_cancel(self._stop_timer_id)
            self._stop_timer_id = self._root.after(
                self._STOP_DEBOUNCE_MS,
                lambda: self._do_stop_notify(),
            )
        elif event_type == "attention":
            if self._attention_timer_id is not None:
                self._root.after_cancel(self._attention_timer_id)
            self._attention_timer_id = self._root.after(
                self._ATTENTION_DEBOUNCE_MS,
                lambda: self._do_attention_notify(),
            )

    def _do_stop_notify(self):
        """真正执行 Stop 通知"""
        self._stop_timer_id = None
        s = self._settings
        now = time.time()

        # 响应时间过滤：距上次通知不足阈值则跳过
        if s.response_time_enabled and self._last_notify_at > 0:
            elapsed = now - self._last_notify_at
            if elapsed < s.response_time_threshold_sec:
                self._debug(f"stop suppressed: elapsed={elapsed:.0f}s < threshold={s.response_time_threshold_sec}s")
                return

        self._last_notify_at = now
        self._debug(f"DO stop notify: flash={s.flash_enabled} sound_path={s.sound_done_path!r} vol={s.sound_done_volume} email={s.email_enabled}")

        if s.flash_enabled:
            result = self.flash_taskbar(count=3)
            self._debug(f"flash_taskbar result: {result}")

        if s.sound_done_enabled:
            self.play_sound(
                path=s.sound_done_path,
                volume=s.sound_done_volume,
            )
        self._debug("done sound played")

        if s.email_enabled:
            summary = self._get_conversation_summary()
            self.send_email("stop", summary=summary)

    def _do_attention_notify(self):
        """真正执行 Attention 通知"""
        self._attention_timer_id = None
        s = self._settings
        self._debug(f"DO attention notify: flash={s.flash_enabled} sound_path={s.sound_attention_path!r} vol={s.sound_attention_volume}")

        if s.flash_enabled:
            result = self.flash_taskbar(count=3)
            self._debug(f"flash_taskbar result: {result}")

        if s.sound_attention_enabled:
            self.play_sound(
                path=s.sound_attention_path,
                volume=s.sound_attention_volume,
            )
        self._debug("attention sound played")
