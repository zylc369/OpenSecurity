"""代理 IP 池（proxy_pool）：代理IP供应商 提取/缓存/黑名单/域名冷却/轮换历史。

设计依据：requirements/evolve/2026-09-25-proxy-ip-manager.md
两条铁律：
  一（信息完整性）：所有换出口动作必须"agent 发起"或"可查询"——rotate_history
    是 agent 判定限流场景的时间线依据，任何自动路径（如 relay 阈值轮换）
    强制调用 rotate()/set_mode() 记史；
  二（故障域隔离）：凭证缺失不抛异常——返回"未配置"状态，direct 模式不受影响。

域名归一化（normalize_domain）是唯一实现：控制接口的 url 参数与 relay 的
CONNECT 目标 host 共用（收口原则，防冷却表键分裂）。
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from config import (
    DATA_DIR,
    DOMAIN_COOLDOWN_SEC,
    JULIANG_API_KEY_KEY,
    JULIANG_API_URL,
    JULIANG_IP_TTL_SEC,
    JULIANG_TTL_MARGIN_SEC,
    JULIANG_TRADE_NO_KEY,
    ROTATE_HISTORY_LIMIT,
)
from services import config_store
from services.process_lock import atomic_write

# ─── 域名归一化（唯一实现，需求 §5.1 全表）──────────────────


def normalize_domain(raw: str) -> str:
    """从任意 URL/host 形态提取归一化域名；无法提取时抛 ValueError（接口层转 400）。

    规则：任意 scheme 只取 host；host 小写；剥端口/userinfo/trailing dot；
    非 ASCII 转 IDNA；IP/localhost 原样保留。
    """
    if not raw or not isinstance(raw, str):
        raise ValueError("url 必传且非空")
    text = raw.strip()
    if not text:
        raise ValueError("url 必传且非空")
    try:
        parts = urlsplit(text)
        host = parts.hostname
        if host is None:
            if "://" in text:  # 有 scheme 无 host（"https://" / "http:///p"）→ 非法
                raise ValueError("url 含 scheme 但无 host")
            host = urlsplit("//" + text).hostname  # 无 scheme（"target.com[:443]"）补 // 再解析
    except ValueError as e:
        raise ValueError(f"无法解析 url: {e}") from e
    if not host:
        raise ValueError("无法从 url 提取 host")
    host = host.lower().rstrip(".")
    try:
        if not host.isascii():  # IDN → punycode
            host = host.encode("idna").decode("ascii")
    except UnicodeError as e:
        raise ValueError(f"域名 IDNA 编码失败: {e}") from e
    if not host or "/" in host or " " in host:
        raise ValueError(f"非法 host: {host!r}")
    return host


# ─── 数据结构 ──────────────────────────────────────────────


@dataclass
class ProxyInfo:
    ip: str              # "1.2.3.4:5678"
    fetched_at: float
    expire_at: float     # fetched_at + TTL − 余量


@dataclass
class RotateEvent:
    ts: float
    reason: str          # agent_rotate | bad_ip | auto_rotate_35conn | mode_direct_to_proxy | mode_proxy_to_direct
    old: str | None      # 旧出口（"direct" 或 "ip:port"）
    new: str | None


@dataclass
class PoolState:
    current: ProxyInfo | None = None
    bad_ips: list[str] = field(default_factory=list)
    domain_limited: dict[str, float] = field(default_factory=dict)  # {归一化域名: 截止时刻}
    mode: str = "direct"                                            # direct | proxy
    surplus: int = -1
    total_fetched: int = 0
    rotate_history: list[RotateEvent] = field(default_factory=list)


class JuliangError(RuntimeError):
    """供应商 API 调用失败（网络/业务码/凭证）。"""


def _julang_sign(params: dict, key: str) -> str:
    """官方签名：参数 ASCII 字典序 + '&key=' + MD5 小写。"""
    raw = "&".join(f"{k}={v}" for k, v in sorted(params.items())) + f"&key={key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def selftest_sign() -> bool:
    """签名自测：官方文档 §1.2 演示数据（明文→期望 MD5）。"""
    demo_params = {"city_name": 1, "ip_remain": 1, "num": 10,
                   "result_type": "json", "trade_no": "1178311789392776"}
    return _julang_sign(demo_params, "99064631962e4e838dac1143092f6112") == \
        "8f35c3e56bf640cb2597ea2492ca62db"


# ─── IP 池 ────────────────────────────────────────────────


class ProxyPool:
    """唯一簿记与状态实现。单例（模块级 _POOL），路由与 relay 进程内直呼。"""

    def __init__(self, state_path: Path | None = None):
        self._path = state_path or (Path(DATA_DIR) / "proxy_state.json")
        self._state = PoolState()
        self._lock = asyncio.Lock()
        self._load()

    # ── 状态持久化 ──

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            import json
            data = json.loads(self._path.read_text())
            st = PoolState(
                current=ProxyInfo(**data["current"]) if data.get("current") else None,
                bad_ips=list(data.get("bad_ips", [])),
                domain_limited={k: float(v) for k, v in data.get("domain_limited", {}).items()},
                mode=data.get("mode", "direct"),
                surplus=int(data.get("surplus", -1)),
                total_fetched=int(data.get("total_fetched", 0)),
                rotate_history=[RotateEvent(**e) for e in data.get("rotate_history", [])],
            )
            self._state = st
        except (ValueError, KeyError, TypeError):
            self._state = PoolState()  # 状态文件损坏 → 重置（黑名单/冷却重启后重学）

    def _persist(self) -> None:
        import json
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path, json.dumps(asdict(self._state), ensure_ascii=False, indent=1))

    # ── 凭证 ──

    @staticmethod
    def credentials_configured() -> bool:
        cfg = config_store.read_all()
        return bool(cfg.get(JULIANG_TRADE_NO_KEY)) and bool(cfg.get(JULIANG_API_KEY_KEY))

    # ── 供应商提取（3 次指数退避）──

    async def _fetch_from_julang(self) -> tuple[ProxyInfo, int]:
        if not self.credentials_configured():
            raise JuliangError("供应商凭证未配置（控制台配置页填写 JULIANG_TRADE_NO / JULIANG_API_KEY）")
        cfg = config_store.read_all()
        params = {"trade_no": cfg[JULIANG_TRADE_NO_KEY], "num": 1, "pt": 1,
                  "result_type": "json", "ip_remain": 1, "filter": 1}
        params["sign"] = _julang_sign(params, cfg[JULIANG_API_KEY_KEY])
        last_err = ""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(JULIANG_API_URL, params=params)
                    data = resp.json()
                if data.get("code") != 200:
                    raise JuliangError(f"供应商业务错误 {data.get('code')}: {data.get('msg', '')}")
                d = data.get("data") or {}
                first = str((d.get("proxy_list") or [""])[0])
                ip_part, _, remain_part = first.partition(",")
                now = time.time()
                info = ProxyInfo(ip=ip_part, fetched_at=now,
                                 expire_at=now + JULIANG_IP_TTL_SEC - JULIANG_TTL_MARGIN_SEC)
                self._state.current = info
                self._state.surplus = int(d.get("surplus_quantity", -1))
                self._state.total_fetched += 1
                return info, int(remain_part or 0)
            except (httpx.HTTPError, ValueError) as e:
                last_err = f"{type(e).__name__}: {e}"
                await asyncio.sleep(0.5 * (2 ** attempt))
        raise JuliangError(f"供应商 API 重试 3 次失败: {last_err}")

    # ── 对外方法 ──

    def _usable(self) -> bool:
        cur = self._state.current
        return bool(cur) and cur.expire_at > time.time() and cur.ip not in self._state.bad_ips

    async def get(self, force_new: bool = False) -> ProxyInfo:
        """缓存命中直接复用（省花销核心）；过期/黑名单/force_new 才提取。"""
        async with self._lock:
            if not force_new and self._usable():
                return self._state.current
            info, _ = await self._fetch_from_julang()
            self._persist()
            return info

    async def rotate(self, reason: str) -> ProxyInfo:
        """换出口：旧 IP 淘汰 + 提取新 IP + 记 history（铁律一）。"""
        async with self._lock:
            old = self._state.current.ip if self._state.current else self._state.mode
            if reason == "bad_ip" and self._state.current:
                self._state.bad_ips.append(self._state.current.ip)
            info, _ = await self._fetch_from_julang()
            self._record(reason, old, info.ip)
            self._persist()
            return info

    def mark_bad(self, ip: str, reason: str = "bad_ip") -> None:
        """黑名单登记（rotate(reason=bad_ip) 内部调用；也可单独使用）。"""
        if ip and ip not in self._state.bad_ips:
            self._state.bad_ips.append(ip)
            self._persist()

    def domain_cool(self, domain_raw: str, minutes: float = DOMAIN_COOLDOWN_SEC / 60) -> str:
        """域名进冷却表（归一化后入键）；顺手清理已过期项。"""
        domain = normalize_domain(domain_raw)  # ValueError → 接口层 400
        now = time.time()
        self._state.domain_limited = {
            k: v for k, v in self._state.domain_limited.items() if v > now
        }
        self._state.domain_limited[domain] = now + minutes * 60
        self._persist()
        return domain

    def domain_cooled(self, domain_raw: str) -> bool:
        """relay 出口选择用：该域名当前是否在冷却期（归一化同源）。"""
        domain = normalize_domain(domain_raw)
        until = self._state.domain_limited.get(domain)
        return bool(until and until > time.time())

    def set_mode(self, mode: str) -> str:
        """全局粗开关（校验枚举）；记 history（铁律一）。"""
        if mode not in ("direct", "proxy"):
            raise ValueError("mode 必须为 direct 或 proxy")
        if mode != self._state.mode:
            self._record(f"mode_{self._state.mode}_to_{mode}",
                         self._state.mode, self._state.mode)
            self._state.mode = mode
            self._persist()
        return self._state.mode

    def _record(self, reason: str, old: str | None, new: str | None) -> None:
        self._state.rotate_history.append(
            RotateEvent(ts=time.time(), reason=reason, old=old, new=new))
        if len(self._state.rotate_history) > ROTATE_HISTORY_LIMIT:
            self._state.rotate_history = self._state.rotate_history[-ROTATE_HISTORY_LIMIT:]

    def status(self) -> dict:
        cur = self._state.current
        now = time.time()
        return {
            "mode": self._state.mode,
            "current": cur.ip if cur else None,
            "expire_in_sec": int(cur.expire_at - now) if cur else 0,
            "bad_count": len(self._state.bad_ips),
            "domain_limited": {k: int(v - now) for k, v in self._state.domain_limited.items() if v > now},
            "surplus": self._state.surplus,
            "total_fetched": self._state.total_fetched,
            "credentials_configured": self.credentials_configured(),
            "rotate_history": [asdict(e) for e in self._state.rotate_history],
        }


# 模块级单例（路由/relay 经 get_pool() 取同一实例）
_POOL: ProxyPool | None = None


def get_pool() -> ProxyPool:
    global _POOL
    if _POOL is None:
        _POOL = ProxyPool()
    return _POOL
