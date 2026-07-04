"""更新任务的最大持续分析时间。

用法:
    python update_max_duration.py --max-duration 2

行为:
    读取 $TASK_DIR/.persistence.json（由 create_task_dir.py 创建），
    更新 max_duration_hours 字段。

    --max-duration: 最大持续分析时间（小时），范围 (0, 24]。
                    超出范围时钳位到默认值 6 小时。

    任务目录从 $TASK_DIR 环境变量读取（由 Plugin shell.env hook 注入）。
    .persistence.json 不存在时报错退出（说明 Plugin 初始化未完成）。

依赖: 仅标准库（os, json, argparse）
"""

import os
import json
import argparse

DEFAULT_MAX_DURATION_HOURS = 6
MAX_DURATION_UPPER_BOUND = 24


def update(max_duration_hours):
    task_dir = os.environ.get("TASK_DIR", "")
    if not task_dir:
        print("[!] TASK_DIR 环境变量未设置（Plugin 初始化可能未完成）", flush=True)
        raise SystemExit(1)

    persistence_file = os.path.join(task_dir, ".persistence.json")
    if not os.path.isfile(persistence_file):
        print(f"[!] 持久化配置不存在: {persistence_file}", flush=True)
        print("    这通常意味着 Plugin 任务初始化未完成。请重新发送消息触发初始化。", flush=True)
        raise SystemExit(1)

    # 钳位到合理范围 (0, 24]
    original = max_duration_hours
    if max_duration_hours <= 0 or max_duration_hours > MAX_DURATION_UPPER_BOUND:
        print(f"[!] --max-duration {original} 超出范围 (0, {MAX_DURATION_UPPER_BOUND}]，"
              f"使用默认值 {DEFAULT_MAX_DURATION_HOURS}", flush=True)
        max_duration_hours = DEFAULT_MAX_DURATION_HOURS

    # 读现有配置（保留 resume_count / last_resume_at 等其他字段）
    with open(persistence_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    old_value = data.get("max_duration_hours")
    data["max_duration_hours"] = max_duration_hours

    with open(persistence_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[+] max_duration_hours: {old_value} → {max_duration_hours}", flush=True)
    print(f"[+] 已更新: {persistence_file}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="更新任务的最大持续分析时间"
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        required=True,
        metavar="HOURS",
        help=f"最大持续分析时间（小时），范围 (0, {MAX_DURATION_UPPER_BOUND}]",
    )
    args = parser.parse_args()
    update(max_duration_hours=args.max_duration)
