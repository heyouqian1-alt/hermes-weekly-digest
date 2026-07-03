# 安装与配置指南

## 前提条件

- Python 3.11+
- Hermes Agent（已运行并有会话数据）
- pip

## 安装步骤

### 1. 下载项目

```bash
git clone https://github.com/你的用户名/hermes-weekly-digest.git
cd hermes-weekly-digest
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

依赖清单：
| 包 | 用途 | 大小 |
|----|------|------|
| `fpdf2` | PDF 生成 | 轻量 |
| `Pillow` | 亚麻纸纹理生成 | 常用 |
| `PyYAML` | 配置文件解析 | 标准 |
| `requests` | HTTP（预留） | 标准 |

### 3. 配置

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，至少需要设置：

```yaml
# Hermes profiles 目录
# Windows: C:\Users\你的用户名\AppData\Local\hermes\profiles
# macOS:   ~/.hermes/profiles
# Linux:   ~/.hermes/profiles
profiles_dir: "C:\\Users\\YourName\\AppData\\Local\\hermes\\profiles"

# 可选：为 profile 起别名（增强 LLM 报告可读性）
profile_info:
  default:
    role: "默认助手"
    model: "qwen-3.6"
    platform: "CLI"
```

### 4. 验证

```bash
python scripts/weekly-digest.py --force
```

如果输出一个 JSON 文件路径，说明配置正确。

## 平台注意事项

### Windows
- 路径用双反斜杠 `\\` 或正斜杠 `/`
- 确保 Python 和 pip 在 PATH 中
- 微软雅黑字体会被自动检测用于 PDF

### macOS
- 需要安装中文字体（系统自带「苹方」）
- 如果 PDF 中文显示异常，修改 `md-to-pdf.py` 中的 `FONT_CANDIDATES`

### Linux
- 需要安装中文字体：`apt install fonts-noto-cjk`
- 修改 `md-to-pdf.py` 中的 `FONT_CANDIDATES` 添加 Noto Sans CJK 路径
