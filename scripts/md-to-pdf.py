#!/usr/bin/env python3
"""
md-to-pdf.py — Markdown 经典报纸风格 PDF 生成器

用法：
  python md-to-pdf.py <输入.md> [输出.pdf]

风格：经典财经报纸（亚麻纸底色 + 棕褐色系 + 报头 + 双栏分割线）

依赖：fpdf2, Pillow, PyYAML
"""

import sys
import os
import re
import io
import json
import random
from pathlib import Path
from fpdf import FPDF
from PIL import Image, ImageFilter

# ==================== 字体发现 ====================

FONT_CANDIDATES = [
    ("C:/Windows/Fonts/msyh.ttc", "msyh"),
    ("C:/Windows/Fonts/msyhbd.ttc", "msyhbd"),
    ("C:/Windows/Fonts/SourceHanSansCN-Regular.otf", "shs"),
    ("C:/Windows/Fonts/SourceHanSansCN-Bold.otf", "shsbd"),
    ("C:/Windows/Fonts/simsun.ttc", "simsun"),
    ("C:/Windows/Fonts/simhei.ttf", "simhei"),
]


def find_fonts():
    """查找可用中文字体"""
    result = {"regular": None, "bold": None}
    for path, name in FONT_CANDIDATES:
        if os.path.exists(path):
            if name == "msyh":
                result["regular"] = path
            elif name == "msyhbd" and not result["bold"]:
                result["bold"] = path
            elif not result["regular"]:
                result["regular"] = path
            elif not result["bold"] and "bold" in name.lower():
                result["bold"] = path
        if result["regular"] and result["bold"]:
            break
    if result["regular"] and not result["bold"]:
        result["bold"] = result["regular"]
    return result


# ==================== Emoji 替换 ====================

EMOJI_MAP = {
    "\U0001f4ca": "[数据]",
    "\U0001f916": "[智能体]",
    "\U0001f947": "[冠军]",
    "\u2705": "[OK]",
    "\u274c": "[X]",
    "\U0001f4c1": "[文件]",
    "\U0001f4a1": "[提示]",
    "\U0001f534": "[红]",
    "\U0001f7e1": "[黄]",
    "\U0001f7e2": "[绿]",
    "\U0001f48e": "[钻石]",
    "\U0001f3c5": "[金牌]",
    "\u2501": "\u2500",
    "\U0001f4c8": "[上升]",
}


def replace_emoji(text):
    """替换 PDF 不支持的 emoji 为文字"""
    for emoji, replacement in EMOJI_MAP.items():
        text = text.replace(emoji, replacement)
    return text


# ==================== 亚麻纸纹理 ====================

_linen_cache = {}  # {bg_hex: (tile_path, bytes_buffer)}


def _get_linen_page(base_color_hex="#EBE0CE"):
    """
    生成 A4 尺寸亚麻纸纹理（缓存复用，只生成一次）
    纹理：200x200 tile，经线 + 纬线 + 随机噪点 + GaussianBlur
    """
    if base_color_hex in _linen_cache:
        return _linen_cache[base_color_hex]

    hexc = base_color_hex.lstrip("#")
    base_color = tuple(int(hexc[i:i+2], 16) for i in (0, 2, 4))
    cache_dir = Path(__file__).parent / ".digest_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    tile_path = cache_dir / f"linen_{hexc}.png"

    # 生成 tileable 纹理
    size = 200
    img = Image.new("RGB", (size, size), base_color)
    pixels = img.load()
    rng = random.Random(42)  # 固定种子保证可复现

    for i in range(size):
        for j in range(size):
            r, g, b = base_color
            # 经线（水平纺织纹）
            if i % 7 < 1:
                r -= 5; g -= 5; b -= 5
            elif i % 7 < 2:
                r -= 2; g -= 2; b -= 2
            # 纬线（垂直纺织纹）
            if j % 7 < 1:
                r -= 4; g -= 4; b -= 4
            elif j % 7 < 2:
                r -= 1; g -= 1; b -= 1
            # 纸纤维噪点
            noise = rng.randint(-2, 2)
            pixels[i, j] = (
                max(0, min(255, r + noise)),
                max(0, min(255, g + noise)),
                max(0, min(255, b + noise)),
            )

    # 模糊柔化 → 织物质感
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    img.save(tile_path, "PNG")

    # 平铺到 A4 全页 (595x842 @ 72dpi)
    a4_w, a4_h = 595, 842
    full = Image.new("RGB", (a4_w, a4_h), base_color)
    for tx in range(0, a4_w, size):
        for ty in range(0, a4_h, size):
            full.paste(img, (tx, ty))

    buf = io.BytesIO()
    full.save(buf, format="PNG")
    buf.seek(0)
    _linen_cache[base_color_hex] = (str(tile_path), buf)
    return _linen_cache[base_color_hex]


# ==================== Markdown 解析 ====================


def parse_markdown(md_text):
    """将 Markdown 文本解析为结构化块列表"""
    blocks = []
    lines = md_text.split("\n")
    i = 0
    in_code = False
    code_buf = []

    while i < len(lines):
        line = lines[i]

        # 代码块
        if line.strip().startswith("```"):
            if in_code:
                blocks.append(("code", "\n".join(code_buf)))
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # 空行跳过
        if not line.strip():
            i += 1
            continue

        # 标题
        if line.strip().startswith("#"):
            level = len(re.match(r'^#+', line.strip()).group())
            blocks.append(("h" + str(level), line.strip()))
            i += 1
            continue

        # 水平线
        if re.match(r'^[-*=]{3,}$', line.strip()):
            blocks.append(("hr", ""))
            i += 1
            continue

        # 列表项
        if re.match(r'^[\s]*[*\+\-] ', line) and not line.strip().startswith("**"):
            blocks.append(("bullet", line))
            i += 1
            continue

        # 引用
        if line.strip().startswith(">"):
            blocks.append(("quote", re.sub(r'^>\s?', '', line).strip()))
            i += 1
            continue

        # 表格（检测表头 + 分隔行）
        if '|' in line.strip() and i + 1 < len(lines) and re.match(r'^[\s|:-]+$', lines[i + 1].strip()):
            headers = [h.strip() for h in line.strip().split('|') if h.strip()]
            i += 2  # 跳过表头和分隔行
            rows = []
            while i < len(lines) and lines[i].strip() and '|' in lines[i]:
                row = [c.strip() for c in lines[i].strip().split('|') if c.strip()]
                if row:
                    rows.append(row)
                i += 1
            blocks.append(("table", {"headers": headers, "rows": rows}))
            continue

        # 普通段落（合并连续非空行）
        para = []
        while (i < len(lines)
               and lines[i].strip()
               and not lines[i].strip().startswith("#")
               and not re.match(r'^[\s]*[*\+\-] ', lines[i])
               and not lines[i].strip().startswith("```")
               and not re.match(r'^[-*=]{3,}$', lines[i].strip())):
            if lines[i].strip():
                para.append(lines[i].strip())
            i += 1
        if para:
            blocks.append(("p", " ".join(para)))
            continue

        i += 1

    return blocks


# ==================== 经典报纸风格定义 ====================

STYLE = {
    # 背景：亚麻纸底色
    "bg_color": "#EBE0CE",

    # 报头栏
    "masthead_bg": (200, 185, 160),
    "masthead_text": (35, 30, 20),
    "masthead_font_size": 22,
    "issue_font_size": 7,

    # 标题颜色
    "h1": (22, 18, 10), "h1_size": 18,
    "h2": (45, 35, 20), "h2_size": 14,
    "h3": (60, 48, 28), "h3_size": 11.5,

    # 正文颜色
    "body": (50, 42, 30), "body_size": 9,
    "bullet": (50, 42, 30), "bullet_size": 8.5,

    # 引用块
    "quote_text": (100, 85, 65), "quote_bg": (230, 218, 198),

    # 代码块
    "code_text": (80, 70, 55), "code_bg": (220, 210, 190),

    # 分割线
    "hr": (160, 145, 125), "hr_thick": 0.5,

    # 页眉页脚
    "header_text": (120, 108, 90),
    "footer_text": (140, 128, 110),

    # 表格
    "table_border": (200, 190, 175),
}


# ==================== PDF 生成器 ====================


class NewspaperPDF(FPDF):
    """经典财经报纸风格 PDF 生成器"""

    def __init__(self, font_path, font_bold_path):
        super().__init__("P", "mm", "A4")
        self.font_path = font_path
        self.font_bold_path = font_bold_path or font_path
        self.set_auto_page_break(auto=True, margin=22)
        self.set_left_margin(15)
        self.add_font("CN", "", font_path)
        self.add_font("CN", "B", self.font_bold_path)
        self._first_page = True
        self._issue = self._gen_issue()

    def _gen_issue(self):
        """生成期号标识"""
        import datetime
        return f"Vol.{datetime.date.today().strftime('%Y%m')} No.{datetime.date.today().day}"

    def _bg(self):
        """绘制亚麻纸背景"""
        tile_path, buf = _get_linen_page(STYLE["bg_color"])
        buf.seek(0)
        self.image(buf, 0, 0, 210, 297)

    def _masthead(self):
        """绘制报头栏"""
        self.set_fill_color(*STYLE["masthead_bg"])
        self.rect(15, 10, 180, 18, 'F')
        self.set_text_color(*STYLE["masthead_text"])
        self.set_xy(15, 12)
        self.set_font("CN", "B", STYLE["masthead_font_size"])
        self.cell(90, 8, "WEEKLY DIGEST", align="L")
        self.set_font("CN", "", STYLE["issue_font_size"])
        self.cell(90, 8, self._issue, align="R")
        self.ln(18)

    def header(self):
        self._bg()
        if self.page_no() > 1:
            self.set_font("CN", "", 6.5)
            self.set_text_color(*STYLE["header_text"])
            self.cell(0, 4, f"WEEKLY DIGEST | {self._issue} | Page {self.page_no()}", align="R")
            self.ln(6)

    def footer(self):
        self.set_y(-14)
        self.set_font("CN", "", 6.5)
        self.set_text_color(*STYLE["footer_text"])
        self.set_draw_color(*STYLE["hr"])
        self.set_line_width(0.3)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(2)
        self.cell(0, 6, f"Weekly Digest -- {self._issue} -- {self.page_no()}", align="C")

    # ---- 内容渲染 ----

    def write_heading(self, text, level=1):
        """渲染标题"""
        clean = re.sub(r'^#{1,6}\s*|\*\*|__', '', text).strip()

        # 首页绘制报头
        if self._first_page and level == 1:
            self._masthead()
            self._first_page = False

        if level == 1:
            self.ln(2)
            # 分隔线
            self.set_draw_color(*STYLE["hr"])
            self.set_line_width(0.8)
            self.line(15, self.get_y(), 195, self.get_y())
            self.ln(4)
            self.set_font("CN", "B", STYLE["h1_size"])
            self.set_text_color(*STYLE["h1"])
            self.multi_cell(0, 8, clean)
            self.ln(2)
            # 分隔线
            self.set_draw_color(*STYLE["hr"])
            self.set_line_width(0.4)
            self.line(15, self.get_y(), 195, self.get_y())
            self.ln(3)

        elif level == 2:
            self.ln(2)
            self.set_font("CN", "B", STYLE["h2_size"])
            self.set_text_color(*STYLE["h2"])
            self.multi_cell(0, 7, clean)
            self.ln(1)

        elif level == 3:
            self.ln(1)
            self.set_font("CN", "B", STYLE["h3_size"])
            self.set_text_color(*STYLE["h3"])
            self.multi_cell(0, 6, clean)
            self.ln(1)

    def write_paragraph(self, text):
        """渲染段落，自动识别日期行"""
        clean = text.strip()
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
        clean = re.sub(r'__([^_]+)__', r'\1', clean)
        clean = re.sub(r'`([^`]+)`', r'\1', clean)

        # 检测日期行（如 "6/28~6/30"、"7/2（周三）-- 系统崩溃日"）
        date_pattern = re.match(r'^(\d{1,2}/\d{1,2}(?:[~\-\u2013]\d{1,2}/\d{1,2})?)\s*(.*)', clean)
        if date_pattern:
            self.set_font("CN", "B", STYLE["body_size"] + 1)
            self.set_text_color(*STYLE["h2"])
            self.set_x(15)
            self.multi_cell(0, 6, clean)
            self.ln(0.5)
            return

        self.set_font("CN", "", STYLE["body_size"])
        self.set_text_color(*STYLE["body"])
        self.set_x(15)
        self.multi_cell(0, 4.5, clean)
        self.ln(1)

    def write_bullet(self, text):
        """渲染列表项"""
        clean = text.strip()
        clean = re.sub(r'^[\s]*[*\+\-]\s+', '', clean)
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
        self.set_font("CN", "", STYLE["bullet_size"])
        self.set_text_color(*STYLE["bullet"])
        self.set_x(15)
        self.multi_cell(0, 5, clean)
        self.ln(0.3)

    def write_horizontal_rule(self):
        """渲染水平分割线"""
        self.ln(2)
        self.set_draw_color(*STYLE["hr"])
        self.set_line_width(0.4)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(4)

    def write_quote(self, text):
        """渲染引用块"""
        self.set_font("CN", "", 9)
        self.set_text_color(*STYLE["quote_text"])
        self.set_fill_color(*STYLE["quote_bg"])
        self.multi_cell(0, 5, f"  {text}", fill=True)
        self.ln(1.5)

    def write_table(self, table_data):
        """渲染表格（紧凑行高 + 交替行背景 + 自动分页）"""
        headers = table_data["headers"]
        rows = table_data["rows"]
        if not headers or not rows:
            return

        n_cols = len(headers)
        avail = 180

        # 列宽分配
        if n_cols <= 3:
            prop = [0.15, 0.12, 0.73]
            widths = [avail * p for p in prop[:n_cols]]
        else:
            widths = [avail / n_cols] * n_cols

        self.ln(1)

        # 分页检查
        if self.get_y() + 18 > self.h - 18:
            self.add_page()

        # 表头行
        self.set_fill_color(200, 185, 160)
        self.set_text_color(45, 40, 33)
        self.set_font("CN", "B", STYLE["body_size"])
        self.set_x(15)
        for i, h in enumerate(headers):
            self.cell(widths[i], 6, str(h), fill=True, border=1, align="C")
        self.ln(1)

        # 数据行
        self.set_text_color(*STYLE["body"])
        self.set_font("CN", "", STYLE["body_size"])
        line_h = STYLE["body_size"] * 0.95
        min_row_h = line_h + 2

        for ri, row in enumerate(rows):
            cell_texts = []
            max_lines = 1
            for ci in range(min(n_cols, len(row))):
                txt = str(row[ci]) if ci < len(row) else ""
                cell_texts.append(txt)
                if widths[ci] > 0:
                    char_w = self.get_string_width("\u4e2d")
                    if char_w <= 0:
                        char_w = 5.0
                    chars_per_line = max(1, int((widths[ci] - 4) / char_w))
                    lines = max(1, len(txt) // chars_per_line + (1 if len(txt) % chars_per_line > 0 else 0))
                    max_lines = max(max_lines, lines)

            row_h = max(min_row_h, max_lines * line_h)
            row_h = min(row_h, line_h * 8)  # 限制最大行高

            # 分页检查
            if self.get_y() + row_h + 2 > self.h - 18:
                self.add_page()

            # 交替行背景
            if ri % 2 == 1:
                self.set_fill_color(228, 218, 200)
            else:
                self.set_fill_color(235, 224, 206)

            # 画单元格
            self.set_draw_color(210, 198, 182)
            y_start = self.get_y()
            x_pos = 15
            for ci in range(min(n_cols, len(cell_texts))):
                self.set_xy(x_pos, y_start)
                if ci == 0:
                    self.set_font("CN", "B", STYLE["body_size"])
                else:
                    self.set_font("CN", "", STYLE["body_size"])
                self.rect(x_pos, y_start, widths[ci], row_h, 'DF')
                self.set_xy(x_pos + 1.5, y_start + 1)
                self.multi_cell(widths[ci] - 3, line_h, cell_texts[ci], border=0, align="L")
                x_pos += widths[ci]
            self.set_y(y_start + row_h)
        self.ln(1)

    def write_code(self, text):
        """渲染代码块"""
        self.set_font("CN", "", 7.5)
        self.set_text_color(*STYLE["code_text"])
        self.set_fill_color(*STYLE["code_bg"])
        lines = text.strip().split("\n")
        for line in lines:
            if line.startswith("```"):
                continue
            self.multi_cell(0, 4.5, f"  {line}", fill=True)
            self.ln(0)
        self.ln(1.5)


# ==================== 版本号管理 ====================

_version_counter = {}


def _get_next_version(stem):
    """为输出文件自动递增版本号"""
    cache_dir = Path(__file__).parent / ".digest_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    vfile = cache_dir / ".pdf_version_counter.json"
    counter = {}
    if vfile.exists():
        try:
            with open(vfile) as f:
                counter = json.load(f)
        except Exception:
            pass
    n = counter.get(stem, 0) + 1
    counter[stem] = n
    with open(vfile, "w") as f:
        json.dump(counter, f)
    return n


# ==================== 主转换函数 ====================


def convert(md_path, pdf_path=None):
    """将 Markdown 文件转换为经典报纸风格 PDF"""
    if pdf_path is None:
        stem = Path(md_path).stem
        ver = _get_next_version(stem)
        pdf_path = Path(md_path).parent / f"{stem}-classic_v{ver}.pdf"

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    # 替换 emoji（PDF 标准字体不支持 emoji）
    md_text = replace_emoji(md_text)

    # 查找字体
    fonts = find_fonts()
    if not fonts["regular"]:
        print("��� 未找到中文字体！请安装微软雅黑或思源黑体。")
        return None

    # 生成 PDF
    pdf = NewspaperPDF(fonts["regular"], fonts["bold"])
    pdf.add_page()

    blocks = parse_markdown(md_text)
    for block_type, content in blocks:
        if block_type == "h1":
            pdf.write_heading(content, 1)
        elif block_type == "h2":
            pdf.write_heading(content, 2)
        elif block_type == "h3":
            pdf.write_heading(content, 3)
        elif block_type == "p":
            pdf.write_paragraph(content)
        elif block_type == "bullet":
            pdf.write_bullet(content)
        elif block_type == "hr":
            pdf.write_horizontal_rule()
        elif block_type == "quote":
            pdf.write_quote(content)
        elif block_type == "code":
            pdf.write_code(content)
        elif block_type == "table":
            pdf.write_table(content)

    pdf.output(str(pdf_path))
    print(f"[classic] {pdf_path}")
    return str(pdf_path)


# ==================== 入口 ====================


def main():
    if len(sys.argv) < 2:
        print("用法：python md-to-pdf.py <输入.md> [输出.pdf]")
        print("  不指定输出路径时，自动生成带版本号的 PDF 文件")
        sys.exit(1)

    md_path = sys.argv[1]
    if not os.path.exists(md_path):
        print(f"��� 找不到文件：{md_path}")
        sys.exit(1)

    pdf_path = sys.argv[2] if len(sys.argv) > 2 else None
    result = convert(md_path, pdf_path)
    if result:
        print(result)


if __name__ == "__main__":
    main()
