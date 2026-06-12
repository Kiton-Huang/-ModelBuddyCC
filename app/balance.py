"""
余额查询 — 支持 DeepSeek / Kimi 等厂商
"""
import ssl
import json
import time
import urllib.request
import urllib.error
from typing import Optional


def _parse_deepseek_balance(data: dict) -> str:
    infos = data.get("balance_infos", [])
    if infos:
        info = infos[0]
        total = info.get("total_balance", "?")
        currency = info.get("currency", "CNY")
        return f"{total} {currency}"
    return "未知"


def _parse_kimi_balance(data: dict) -> str:
    d = data.get("data", data)
    for key in ("available_balance", "total_balance", "balance"):
        val = d.get(key)
        if val is not None and val != "":
            return f"{val} 元"
    return "未知"


# 注册表：域名关键词 → (厂商名, 余额API地址, 响应解析函数)
BALANCE_PROVIDERS: dict[str, tuple[str, str, callable]] = {
    "api.deepseek.com": ("DeepSeek", "https://api.deepseek.com/user/balance", _parse_deepseek_balance),
    "api.moonshot.cn": ("Kimi", "https://api.moonshot.cn/v1/users/me/balance", _parse_kimi_balance),
}


def detect_provider(base_url: str) -> Optional[tuple[str, str, callable]]:
    """根据 base_url 匹配对应的余额查询厂商"""
    for domain, provider in BALANCE_PROVIDERS.items():
        if domain in base_url:
            return provider
    return None


# 余额缓存：{(base_url, api_key_hash): (result, timestamp)}，缓存 60 秒
_balance_cache: dict[tuple, tuple[dict, float]] = {}
_BALANCE_CACHE_TTL = 60


def _hash_key(api_key: str) -> str:
    return str(hash(api_key))


def check_balance(base_url: str, api_key: str, force: bool = False) -> dict:
    """查询余额，返回 {'success': bool, 'balance': str, 'provider': str, 'error': str}"""
    cache_key = (base_url, _hash_key(api_key))
    if not force:
        cached = _balance_cache.get(cache_key)
        if cached and (time.time() - cached[1]) < _BALANCE_CACHE_TTL:
            return cached[0]
    provider = detect_provider(base_url)
    if not provider:
        return {"success": False, "balance": "", "provider": "未知", "error": "未找到对应的余额查询接口"}

    name, url, parser = provider
    try:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            balance = parser(data)
            result = {"success": True, "balance": balance, "provider": name, "error": ""}
            _balance_cache[cache_key] = (result, time.time())
            return result
    except urllib.error.HTTPError as e:
        return {"success": False, "balance": "", "provider": name, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"success": False, "balance": "", "provider": name, "error": str(e)}
