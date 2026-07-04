#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CTF 赛事速览：拉取 CTFtime 比赛，分「进行中」「即将开始」两个表格输出。

排序:
  进行中   — 剩余时间降序（剩余多的在前）
  即将开始 — 开赛时间升序（最近在前），权重 ≥ 30 标 ⭐
过滤:
  即将开始仅线上（onsite=true 已剔除）；进行中保留全部（含现场）
  持续 > 14 天视为非典型（练习平台/长期 challenge），剔除
窗口: now-7d ~ now+30d
数据源: https://ctftime.org/api/v1/events/

仅依赖标准库。用法: python3 ctf_events.py
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

API = "https://ctftime.org/api/v1/events/"
USER_AGENT = "Mozilla/5.0 (compatible; ctf-events-cli/1.0)"
WINDOW_PAST_DAYS = 7
WINDOW_FUTURE_DAYS = 30
MAX_DURATION_DAYS = 14      # 超过视为非典型(练习平台),剔除
WEIGHT_STAR = 30.0          # 权重 ≥ 此值在标题前标 ⭐
REQ_TIMEOUT = 20


def fetch_events():
    """拉取时间窗口内的 CTFtime events。窗口与 event 有交集即返回。"""
    now = int(time.time())
    start = now - WINDOW_PAST_DAYS * 86400
    finish = now + WINDOW_FUTURE_DAYS * 86400
    url = f"{API}?limit=200&start={start}&finish={finish}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_local(dt):
    """转本地时区，显示 月-日 时:分。"""
    return dt.astimezone().strftime("%m-%d %H:%M")


def fmt_date_range(s, f):
    """持续: 几号~几号（同一天只显示一个日期）。"""
    s_l, f_l = s.astimezone(), f.astimezone()
    if s_l.date() == f_l.date():
        return s_l.strftime("%m-%d")
    return f"{s_l.strftime('%m-%d')}~{f_l.strftime('%m-%d')}"


def fmt_remaining(finish, now):
    """距结束的剩余时间: X天X小时 / X小时Y分钟 / 不足1分钟。"""
    secs = int((finish - now).total_seconds())
    if secs <= 0:
        return "已结束"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{mins}分钟"
    if mins <= 0:
        return "不足1分钟"
    return f"{mins}分钟"


def fmt_weight(w):
    w = w or 0.0
    return ("⭐" if w >= WEIGHT_STAR else "") + f"{w:g}"


# 赛制/参赛限制的中文标注映射; 未知值原样返回(不强行翻译,避免猜错)
FORMAT_LABELS = {
    "Jeopardy": "Jeopardy（解题赛）",
    "Attack-Defense": "Attack-Defense（攻防赛）",
    "King of the Hill": "King of the Hill（占点赛）",
}
RESTRICTION_LABELS = {
    "Open": "Open（开放）",
    "Restricted": "Restricted（限制）",
    "Individual": "Individual（限个人）",
}


def fmt_format(fmt):
    return FORMAT_LABELS.get(fmt, fmt or "-")


def fmt_restriction(r):
    return RESTRICTION_LABELS.get(r, r or "-")


def venue(e):
    return "现场" if e.get("onsite") else "线上"


def title(e):
    return e.get("title", "(无标题)")


def link(e):
    return e.get("ctftime_url") or e.get("url") or ""


def classify(events, now):
    """返回 (ongoing, upcoming)。即将开始过滤现场; 进行中保留全部。"""
    ongoing, upcoming = [], []
    for e in events:
        try:
            s = parse_dt(e["start"])
            f = parse_dt(e["finish"])
        except (KeyError, ValueError):
            continue
        if (f - s).total_seconds() / 86400 > MAX_DURATION_DAYS:
            continue  # 非典型(练习平台)
        if s <= now <= f:
            ongoing.append((e, s, f))
        elif s > now:
            if e.get("onsite"):
                continue  # 即将开始: 只线上
            upcoming.append((e, s, f))
    return ongoing, upcoming


def render_ongoing(rows, now):
    if not rows:
        return "### 🔴 进行中\n\n暂无进行中的比赛。\n"
    out = ["### 🔴 进行中（按剩余时间降序）\n"]
    out.append("| 标题 | 剩余 | 持续 | 赛制 | 线上/现场 | 地点 | 权重 | 链接 |")
    out.append("|------|------|------|------|----------|------|------|------|")
    for e, s, f in rows:
        loc = e.get("location") or "-"
        out.append(
            f"| {title(e)} | {fmt_remaining(f, now)} | {fmt_date_range(s, f)} | "
            f"{fmt_format(e.get('format'))} | {venue(e)} | {loc} | "
            f"{fmt_weight(e.get('weight', 0))} | {link(e)} |"
        )
    return "\n".join(out) + "\n"


def render_upcoming(rows):
    if not rows:
        return "### 🟢 即将开始\n\n暂无即将开始的线上比赛。\n"
    out = ["### 🟢 即将开始（按开赛时间升序，⭐=权重≥30）\n"]
    out.append("| 标题 | 开赛(本地时区) | 持续 | 赛制 | 参赛限制 | 权重 | 链接 |")
    out.append("|------|-----------|------|------|------|------|------|")
    for e, s, f in rows:
        out.append(
            f"| {title(e)} | {fmt_local(s)} | {fmt_date_range(s, f)} | "
            f"{fmt_format(e.get('format'))} | {fmt_restriction(e.get('restrictions'))} | "
            f"{fmt_weight(e.get('weight', 0))} | {link(e)} |"
        )
    return "\n".join(out) + "\n"


def main():
    try:
        events = fetch_events()
    except Exception as ex:
        print(f"❌ 拉取 CTFtime 数据失败: {ex}", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    ongoing, upcoming = classify(events, now)
    # 进行中: 剩余时间降序（剩余多的在前）
    ongoing.sort(key=lambda x: (x[2] - now).total_seconds(), reverse=True)
    # 即将开始: 开赛时间升序
    upcoming.sort(key=lambda x: x[1])

    local = datetime.now().astimezone()
    tz_name = local.strftime("%Z") or "本地"
    print(f"> 时间: {local.strftime('%Y-%m-%d %H:%M')} ({tz_name}) | 数据源: CTFtime\n")
    print(render_ongoing(ongoing, now))
    print(render_upcoming(upcoming))


if __name__ == "__main__":
    main()
