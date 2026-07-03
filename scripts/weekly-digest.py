#!/usr/bin/env python3
"""
weekly-digest.py — Hermes 跨 Profile 周报数据收集器

作用：
  每周一自动扫描所有 Hermes Agent 的会话记录和技能/记忆变更，
  输出结构化 JSON 数据，供 LLM 生成叙事报告。

用法：
  python weekly-digest.py                     # 周一守护模式（非周一则静默退出）
  python weekly-digest.py --force             # 强制生成（跳过周一检查）
  python weekly-digest.py --config config.yaml # 指定配置文件

定时建议：
  配合 cron 每 4 小时执行一次，脚本自带周一守护：
  - 不是周一 → 静默退出（无输出，不推送）
  - 是周一但本周已生成过 → 静默退出
  - 是周一且本周未生成 → 输出 JSON 文件路径 → 供 LLM 生成报告
"""

import sqlite3
import json
import datetime
import os
import sys
import yaml
from pathlib import Path

# ==================== 默认配置 ====================
DEFAULT_CONFIG = {
    "profiles_dir": "~/.hermes/profiles",      # Hermes profiles 目录
    "desktop_dir": "~/Desktop",                 # 桌面路径（备用）
    "cache_dir": "./.digest_cache",             # 缓存目录（相对脚本所在目录）
    "weekday": 0,                               # 周几触发（0=周一）
    "profiles": {},                             # 空 = 自动发现所有 profile
    "profile_info": {},                         # profile 显示名映射（可选）
}

# ==================== 配置加载 ====================

def load_config(config_path=None):
    """加载配置，优先从命令行指定的 yaml，否则用默认"""
    cfg = dict(DEFAULT_CONFIG)

    if config_path is None:
        # 尝试自动发现 config.yaml
        script_dir = Path(__file__).parent.resolve()
        candidates = [
            Path(config_path) if config_path else None,
            script_dir / "config.yaml",
            script_dir.parent / "config.yaml",
            Path("config.yaml"),
        ]
        for c in candidates:
            if c and c.exists():
                config_path = str(c)
                break

    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
            # 合并（用户配置覆盖默认）
            for k, v in user_cfg.items():
                if v is not None:
                    cfg[k] = v

    # 展开 ~ 路径
    for key in ["profiles_dir", "desktop_dir", "cache_dir"]:
        cfg[key] = str(Path(cfg[key]).expanduser().resolve())

    return cfg


# ==================== Profile 发现 ====================

def find_all_profiles(profiles_dir):
    """扫描磁盘发现所有真实存在的 profile（含幽灵 profile）"""
    profiles = []
    if not os.path.exists(profiles_dir):
        return profiles
    for d in sorted(os.listdir(profiles_dir)):
        dpath = os.path.join(profiles_dir, d)
        if os.path.isdir(dpath) and os.path.exists(os.path.join(dpath, "state.db")):
            profiles.append(d)
    return profiles


# ==================== 周一守护 ====================

def should_run(cfg):
    """判断是否应该执行：周一 + 本周未发送"""
    now = datetime.datetime.now()
    if now.weekday() != cfg["weekday"]:
        return False

    state_file = Path(cfg["cache_dir"]) / ".weekly-digest-state.json"
    this_week = now.isocalendar()[1]
    this_year = now.year

    if state_file.exists():
        try:
            with open(state_file) as f:
                state = json.load(f)
            if state.get("year") == this_year and state.get("week") == this_week:
                return False
        except (json.JSONDecodeError, ValueError) as e:
            pass

    return True


def mark_sent(cfg):
    """标记本周已生成"""
    now = datetime.datetime.now()
    state_file = Path(cfg["cache_dir"]) / ".weekly-digest-state.json"
    Path(cfg["cache_dir"]).mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump({
            "year": now.year,
            "week": now.isocalendar()[1],
            "sent_at": now.isoformat()
        }, f)


# ==================== 数据收集 ====================

def collect_profile_data(profiles_dir, profile, since_ts):
    """收集单个 profile 的完整数据"""
    db_path = os.path.join(profiles_dir, profile, "state.db")
    result = {
        "profile": profile,
        "sessions": [],
        "new_skills": [],
        "new_memories": [],
        "session_count": 0,
    }

    if not os.path.exists(db_path):
        return result

    try:
        conn = sqlite3.connect(db_path)
        conn.text_factory = str

        cur = conn.execute(
            "SELECT id, title, started_at, message_count FROM sessions "
            "ORDER BY started_at DESC LIMIT 200"
        )

        for sid, title, started, msg_count in cur.fetchall():
            if started and isinstance(started, (int, float)):
                started_dt = datetime.datetime.fromtimestamp(started)
            elif started and isinstance(started, str):
                try:
                    started_dt = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
                except:
                    started_dt = None
            else:
                started_dt = None

            if started_dt and started_dt.timestamp() >= since_ts:
                # 取用户消息摘要
                msg_rows = conn.execute(
                    "SELECT role, content FROM messages WHERE session_id = ? "
                    "ORDER BY id LIMIT 8", (sid,)
                ).fetchall()

                user_topics = []
                for role, content in msg_rows:
                    if role == "user" and content:
                        line = content.strip().split("\n")[0][:80]
                        if line:
                            user_topics.append(line)

                result["sessions"].append({
                    "id": sid,
                    "title": str(title or "(未命名)")[:80],
                    "date": started_dt.strftime("%m/%d") if started_dt else "?",
                    "messages": msg_count or 0,
                    "user_topics": user_topics[:6],
                })
                result["session_count"] += 1

        conn.close()
    except Exception as e:
        result["error"] = str(e)

    # === 技能目录扫描 ===
    skills_dir = os.path.join(profiles_dir, profile, "skills")
    if os.path.exists(skills_dir):
        for item in sorted(os.listdir(skills_dir)):
            skill_md = os.path.join(skills_dir, item, "SKILL.md")
            if os.path.isdir(os.path.join(skills_dir, item)) and os.path.exists(skill_md):
                mtime = os.path.getmtime(skill_md)
                if mtime >= since_ts:
                    desc = ""
                    try:
                        with open(skill_md, "r", encoding="utf-8") as f:
                            for line in f:
                                if line.startswith("description:"):
                                    desc = line.split(":", 1)[1].strip().strip('"').strip("'")
                                    break
                    except Exception:
                        pass
                    result["new_skills"].append({"name": item, "description": desc})

    # === 记忆目录扫描 ===
    memories_dir = os.path.join(profiles_dir, profile, "memories")
    if os.path.exists(memories_dir):
        for item in sorted(os.listdir(memories_dir)):
            mem_path = os.path.join(memories_dir, item)
            if item.endswith(".md") and os.path.isfile(mem_path):
                mtime = os.path.getmtime(mem_path)
                if mtime >= since_ts:
                    result["new_memories"].append(item.replace(".md", ""))

    return result


def get_week_range(now=None):
    """返回上周的时间范围"""
    if now is None:
        now = datetime.datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - datetime.timedelta(days=today.weekday())
    last_monday = monday - datetime.timedelta(days=7)
    last_sunday = monday - datetime.timedelta(seconds=1)
    return last_monday.timestamp(), f"{last_monday.strftime('%m/%d')}~{last_sunday.strftime('%m/%d')}"


def run_collection(cfg, profiles_filter=None):
    """主收集流程"""
    since_ts, week_label = get_week_range()
    profiles_dir = cfg["profiles_dir"]

    # 发现 profile
    if profiles_filter:
        all_profiles = [p for p in profiles_filter if os.path.exists(os.path.join(profiles_dir, p, "state.db"))]
    else:
        all_profiles = find_all_profiles(profiles_dir)

    all_data = {
        "generated_at": datetime.datetime.now().isoformat(),
        "week_label": week_label,
        "since_ts": since_ts,
        "agents": [],
        "total_sessions": 0,
        "total_skills": 0,
        "total_memories": 0,
    }

    for profile in sorted(all_profiles):
        data = collect_profile_data(profiles_dir, profile, since_ts)
        # 如果配置了 profile_info，附加便于 LLM 阅读
        if profile in cfg.get("profile_info", {}):
            data["info"] = cfg["profile_info"][profile]
        all_data["agents"].append(data)
        all_data["total_sessions"] += data["session_count"]
        all_data["total_skills"] += len(data["new_skills"])
        all_data["total_memories"] += len(data["new_memories"])

    return all_data, week_label


# ==================== 入口 ====================

def main():
    # 解析命令行
    config_path = None
    force = False
    for arg in sys.argv[1:]:
        if arg == "--force":
            force = True
        elif arg.startswith("--config="):
            config_path = arg.split("=", 1)[1]
        elif arg == "--config" and len(sys.argv) > sys.argv.index(arg) + 1:
            config_path = sys.argv[sys.argv.index(arg) + 1]

    cfg = load_config(config_path)

    # 脚本所在目录（用于解析相对路径的 cache_dir）
    script_dir = Path(__file__).parent.resolve()

    # 如果 cache_dir 是相对路径，相对于脚本目录
    cache_dir = Path(cfg["cache_dir"])
    if not cache_dir.is_absolute():
        cache_dir = script_dir / cache_dir
    cfg["cache_dir"] = str(cache_dir)

    # ===== 周一守护 =====
    if not force and not should_run(cfg):
        return  # 静默退出

    # ===== 收集数据 =====
    all_data, week_label = run_collection(cfg)

    # ===== 保存 JSON =====
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_label = week_label.replace("/", "-").replace("~", "~")
    json_path = cache_dir / f"digest-data-{safe_label}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    # ===== 标记已发送 =====
    if not force:
        mark_sent(cfg)

    # ===== 输出 JSON 路径（cron 会将其注入 LLM 上下文）=====
    print(json_path)


if __name__ == "__main__":
    main()
