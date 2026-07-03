# 工作流：从数据到叙事报告

整个周报系统是 **两步走** 架构：

1. **Step 1** — `weekly-digest.py`（no_agent 脚本）：收集原始数据，输出 JSON
2. **Step 2** — LLM Agent：读 JSON，写叙事报告，调用 `md-to-pdf.py` 转 PDF

---

## 完整流程

### Step 1: 数据收集

```bash
python scripts/weekly-digest.py [--force] [--config config.yaml]
```

输出：JSON 文件路径（如 `.digest_cache/digest-data-06/29~07/05.json`）

数据包含：
- 每个 profile 的会话列表（日期、标题、用户消息摘要）
- 本周新增技能（名称 + description）
- 本周新增记忆

### Step 2: LLM 生成叙事报告

将上述 JSON 路径喂给任何 LLM（Hermes、Claude、GPT...），提示词模板如下：

```
读取这个 JSON 文件，里面包含了过去 7 天所有 Hermes Agent 的活动数据。
你需要为每个 agent 写一段叙事总结，最后写一份综合总报告。

格式：
1. 每个 agent 独立总结（100-200字，自然语言）
2. 技能与成长总览（对比表格）
3. 关键事件时间线
4. 综合汇总

顶部元数据用 【】 括起来，不要用 > 引用语法。

保存为 weekly-report-{label}.md 到桌面。
然后调用 python scripts/md-to-pdf.py "桌面路径/weekly-report-{label}.md" 转成 PDF。
```

### Step 3: PDF 生成

`md-to-pdf.py` 仅支持经典报纸风格，无需 `--style` 参数：

```bash
python scripts/md-to-pdf.py report.md
```

**PDF 特性：**

| 特性 | 说明 |
|------|------|
| 底色 | 亚麻纸纹理（经→纬→噪点→模糊），缓存 PNG 零开销 |
| 报头 | 棕褐色条幅 + 周报标题 |
| 日期行 | 自动识别 `YYYY-MM-DD` 或 `MM/DD` 格式，加粗 |
| 表格 | 紧凑行高 + 交替背景色 |
| Emoji | 自动回退为文字描述 |
| 版本管理 | 同名文件自动递增 `_v1`、`_v2` 后缀 |

**字体自动探测：**

---

## 在 Hermes 中通过 Cron 自动化

### 方式 A：no_agent 模式（仅收集数据）

```bash
hermes cron create "every 4h" \
  --name "周报数据收集" \
  --script "scripts/weekly-digest.py" \
  --deliver local
```

这种方式只收集 JSON，不生成报告。适合与其他工作流配合。

### 方式 B：agent 模式（推荐 — 全自动）

```bash
hermes cron create "every 4h" \
  --name "每周周报(开机即发)" \
  --script "scripts/weekly-digest.py" \
  --prompt "你收到的是周报数据收集脚本的输出。如果为空则静默退出。如果有JSON路径，则读JSON写叙事报告+保存桌面.md+转.pdf" \
  --deliver all
```

### cron 守护逻辑

脚本内置周一守护，非周一自动静默退出（无输出、不推送），所以 cron 可以放心设置每 4 小时运行而不产生垃圾：

| 场景 | 行为 |
|------|------|
| 周二~周日跑 | 静默退出，空输出 |
| 周一第一次跑 | 收集数据 → 输出 JSON → 标记已发 |
| 周一第二次跑 | 检测已发标记 → 静默退出 |

---

## 在 Hermes 中手动触发

```bash
# 强制收集（跳过周一检查）
python scripts/weekly-digest.py --force

# 读 JSON 内容
cat scripts/.digest_cache/digest-data-*.json | head -100

# 仅转 PDF（已有 .md 文件）
python scripts/md-to-pdf.py ~/Desktop/weekly-report-06/29~07/05.md
```
