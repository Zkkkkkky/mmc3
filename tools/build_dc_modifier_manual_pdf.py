from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "DC修改器使用说明.md"
DEFAULT_OUTPUT = ROOT / "output" / "pdf" / "DC修改器使用说明.pdf"
PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 18 * mm
RIGHT_MARGIN = 18 * mm
TOP_MARGIN = 18 * mm
BOTTOM_MARGIN = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN

NAVY = HexColor("#102A43")
BLUE = HexColor("#1677C8")
LIGHT_BLUE = HexColor("#EAF4FC")
PALE_BLUE = HexColor("#F4F9FD")
SLATE = HexColor("#52667A")
TEXT = HexColor("#172B3A")
LINE = HexColor("#CAD8E4")
PALE_GRAY = HexColor("#F5F7F9")
WARNING = HexColor("#FFF5D8")
WARNING_LINE = HexColor("#E0A11A")


def register_fonts() -> None:
    candidates = [
        ("C:/Windows/Fonts/SourceHanSansCN-Normal.ttf", "C:/Windows/Fonts/simhei.ttf"),
        ("C:/Windows/Fonts/Deng.ttf", "C:/Windows/Fonts/Dengb.ttf"),
        ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"),
    ]
    for regular, bold in candidates:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("CNRegular", regular))
            pdfmetrics.registerFont(TTFont("CNBold", bold))
            pdfmetrics.registerFontFamily(
                "CNRegular",
                normal="CNRegular",
                bold="CNBold",
                italic="CNRegular",
                boldItalic="CNBold",
            )
            return
    raise FileNotFoundError("未找到可嵌入的中文字体")


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="CNBold",
            fontSize=28,
            leading=36,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceAfter=3 * mm,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontName="CNRegular",
            fontSize=15,
            leading=22,
            textColor=BLUE,
            alignment=TA_CENTER,
            spaceAfter=5 * mm,
        ),
        "cover_lead": ParagraphStyle(
            "CoverLead",
            parent=base["Normal"],
            fontName="CNRegular",
            fontSize=10.5,
            leading=17,
            textColor=SLATE,
            alignment=TA_CENTER,
        ),
        "toc_title": ParagraphStyle(
            "TocTitle",
            parent=base["Heading1"],
            fontName="CNBold",
            fontSize=24,
            leading=31,
            textColor=NAVY,
            spaceAfter=4 * mm,
        ),
        "toc_note": ParagraphStyle(
            "TocNote",
            parent=base["Normal"],
            fontName="CNRegular",
            fontSize=9.5,
            leading=15,
            textColor=SLATE,
            spaceAfter=7 * mm,
        ),
        "h2": ParagraphStyle(
            "Heading2CN",
            parent=base["Heading2"],
            fontName="CNBold",
            fontSize=17,
            leading=23,
            textColor=NAVY,
            spaceBefore=7 * mm,
            spaceAfter=3.5 * mm,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "Heading3CN",
            parent=base["Heading3"],
            fontName="CNBold",
            fontSize=12.5,
            leading=18,
            textColor=BLUE,
            spaceBefore=3.8 * mm,
            spaceAfter=1.6 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "BodyCN",
            parent=base["BodyText"],
            fontName="CNRegular",
            fontSize=9.7,
            leading=15.2,
            textColor=TEXT,
            alignment=TA_LEFT,
            spaceAfter=2.1 * mm,
            allowWidows=0,
            allowOrphans=0,
        ),
        "list": ParagraphStyle(
            "ListCN",
            parent=base["BodyText"],
            fontName="CNRegular",
            fontSize=9.5,
            leading=14.7,
            textColor=TEXT,
            spaceAfter=1.2 * mm,
        ),
        "caption": ParagraphStyle(
            "CaptionCN",
            parent=base["Normal"],
            fontName="CNRegular",
            fontSize=8.2,
            leading=12,
            textColor=SLATE,
            alignment=TA_CENTER,
        ),
        "table_header": ParagraphStyle(
            "TableHeaderCN",
            parent=base["Normal"],
            fontName="CNBold",
            fontSize=8.5,
            leading=12,
            textColor=colors.white,
        ),
        "table_cell": ParagraphStyle(
            "TableCellCN",
            parent=base["Normal"],
            fontName="CNRegular",
            fontSize=8.3,
            leading=12,
            textColor=TEXT,
        ),
        "callout": ParagraphStyle(
            "CalloutCN",
            parent=base["BodyText"],
            fontName="CNRegular",
            fontSize=9.5,
            leading=15,
            textColor=TEXT,
        ),
        "code": ParagraphStyle(
            "CodeCN",
            parent=base["Code"],
            fontName="CNRegular",
            fontSize=8.5,
            leading=13,
            textColor=NAVY,
        ),
        "feature": ParagraphStyle(
            "FeatureCN",
            parent=base["Normal"],
            fontName="CNBold",
            fontSize=9,
            leading=13,
            textColor=NAVY,
            alignment=TA_CENTER,
        ),
    }


def normalize_dashes(value: str) -> str:
    return value.translate(str.maketrans({"–": "-", "—": "-", "‑": "-", "−": "-"}))


def inline_markup(value: str) -> str:
    escaped = html.escape(normalize_dashes(value), quote=False)
    escaped = re.sub(
        r"`([^`]+)`",
        r'<font name="CNRegular" color="#0B65A5">\1</font>',
        escaped,
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)
    return escaped


def make_heading(text: str, level: int, styles: dict[str, ParagraphStyle], serial: int) -> Paragraph:
    style = styles["h2" if level == 0 else "h3"]
    paragraph = Paragraph(inline_markup(text), style)
    paragraph._toc_level = level  # type: ignore[attr-defined]
    paragraph._toc_text = normalize_dashes(text)  # type: ignore[attr-defined]
    paragraph._bookmark_name = f"heading-{serial}"  # type: ignore[attr-defined]
    return paragraph


def scaled_image(path: Path, max_width: float, max_height: float) -> Image:
    width, height = ImageReader(str(path)).getSize()
    scale = min(max_width / width, max_height / height)
    return Image(str(path), width=width * scale, height=height * scale)


def figure(path: Path, caption: str, styles: dict[str, ParagraphStyle], max_height: float = 92 * mm) -> Table:
    image = scaled_image(path, CONTENT_WIDTH - 6 * mm, max_height)
    rows: list[list[object]] = [[image]]
    if caption:
        rows.append([Paragraph(inline_markup(caption), styles["caption"])])
    table = Table(rows, colWidths=[CONTENT_WIDTH], hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, 0), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 3 * mm),
                ("TOPPADDING", (0, 1), (-1, -1), 1.5 * mm),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 2.5 * mm),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ]
        )
    )
    return table


def callout(text: str, styles: dict[str, ParagraphStyle]) -> Table:
    paragraph = Paragraph(inline_markup(text), styles["callout"])
    table = Table([[paragraph]], colWidths=[CONTENT_WIDTH], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WARNING),
                ("LINEBEFORE", (0, 0), (0, -1), 3, WARNING_LINE),
                ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#E7D39B")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    return table


def markdown_table(lines: list[str], styles: dict[str, ParagraphStyle]) -> Table:
    parsed = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [parsed[0]] + parsed[2:]
    cell_rows: list[list[Paragraph]] = []
    for row_index, row in enumerate(rows):
        style = styles["table_header" if row_index == 0 else "table_cell"]
        cell_rows.append([Paragraph(inline_markup(cell), style) for cell in row])
    column_count = len(cell_rows[0])
    if column_count == 2:
        widths = [CONTENT_WIDTH * 0.30, CONTENT_WIDTH * 0.70]
    elif column_count == 3:
        widths = [CONTENT_WIDTH * 0.22, CONTENT_WIDTH * 0.54, CONTENT_WIDTH * 0.24]
    else:
        widths = [CONTENT_WIDTH / column_count] * column_count
    table = Table(cell_rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style_commands: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
    ]
    for row_index in range(1, len(cell_rows)):
        if row_index % 2 == 0:
            style_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), PALE_GRAY))
    table.setStyle(TableStyle(style_commands))
    return table


def render_markdown(source: str, styles: dict[str, ParagraphStyle]) -> list[object]:
    lines = source.splitlines()
    story: list[object] = []
    heading_serial = 0
    index = 0
    skip_overview_caption = False
    while index < len(lines):
        raw = lines[index].rstrip()
        stripped = raw.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("# "):
            index += 1
            continue
        if stripped.startswith("## "):
            heading_serial += 1
            story.extend(
                [
                    CondPageBreak(105 * mm),
                    make_heading(stripped[3:].strip(), 0, styles, heading_serial),
                ]
            )
            index += 1
            continue
        if stripped.startswith("### "):
            heading_serial += 1
            story.extend(
                [
                    CondPageBreak(23 * mm),
                    make_heading(stripped[4:].strip(), 1, styles, heading_serial),
                ]
            )
            index += 1
            continue
        if stripped.startswith("```"):
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(normalize_dashes(lines[index]))
                index += 1
            index += 1
            block = Preformatted("\n".join(code_lines), styles["code"])
            box = Table([[block]], colWidths=[CONTENT_WIDTH])
            box.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), PALE_GRAY),
                        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                    ]
                )
            )
            story.extend([box, Spacer(1, 2.5 * mm)])
            continue
        image_match = re.fullmatch(r"!\[(.*?)\]\((.*?)\)", stripped)
        if image_match:
            alt_text, relative_path = image_match.groups()
            image_path = ROOT / relative_path
            if image_path.name == "12-project-overview.png":
                skip_overview_caption = True
                index += 1
                continue
            caption = alt_text
            lookahead = index + 1
            while lookahead < len(lines) and not lines[lookahead].strip():
                lookahead += 1
            if lookahead < len(lines):
                caption_match = re.fullmatch(r"\*(.+)\*", lines[lookahead].strip())
                if caption_match:
                    caption = caption_match.group(1)
                    index = lookahead
            if not image_path.exists():
                raise FileNotFoundError(f"说明图片不存在：{image_path}")
            story.extend([figure(image_path, caption, styles), Spacer(1, 3 * mm)])
            index += 1
            continue
        if skip_overview_caption and re.fullmatch(r"\*(.+)\*", stripped):
            skip_overview_caption = False
            index += 1
            continue
        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip()[1:].strip())
                index += 1
            story.extend([callout(" ".join(quote_lines), styles), Spacer(1, 3 * mm)])
            continue
        if stripped.startswith("|"):
            table_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            story.extend([markdown_table(table_lines, styles), Spacer(1, 3 * mm)])
            continue
        list_match = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        bullet_match = re.match(r"^-\s+(.+)$", stripped)
        if list_match or bullet_match:
            ordered = list_match is not None
            items: list[ListItem] = []
            while index < len(lines):
                candidate = lines[index].strip()
                match = re.match(r"^\d+\.\s+(.+)$", candidate) if ordered else re.match(r"^-\s+(.+)$", candidate)
                if not match:
                    break
                items.append(ListItem(Paragraph(inline_markup(match.group(1)), styles["list"])))
                index += 1
            story.append(
                ListFlowable(
                    items,
                    bulletType="1" if ordered else "bullet",
                    start="1" if ordered else None,
                    leftIndent=6 * mm,
                    bulletFontName="CNRegular",
                    bulletFontSize=9,
                    bulletColor=BLUE,
                    spaceAfter=3 * mm,
                )
            )
            continue
        if re.fullmatch(r"\*(.+)\*", stripped):
            story.append(Paragraph(inline_markup(stripped[1:-1]), styles["caption"]))
            index += 1
            continue
        paragraph_lines = [stripped]
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if not candidate:
                break
            if (
                candidate.startswith("#")
                or candidate.startswith(">")
                or candidate.startswith("|")
                or candidate.startswith("```")
                or candidate.startswith("![")
                or re.match(r"^(?:\d+\.|-)\s+", candidate)
            ):
                break
            paragraph_lines.append(candidate)
            index += 1
        story.append(Paragraph(inline_markup(" ".join(paragraph_lines)), styles["body"]))
    return story


class ManualDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str):
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=LEFT_MARGIN,
            rightMargin=RIGHT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
            title="新DC篇完整修改器 3.0：图文使用说明",
            author="新DC篇完整修改器项目",
            subject="扩容版第二次机器人大战 ROM 修改器使用说明",
        )
        frame = Frame(
            LEFT_MARGIN,
            BOTTOM_MARGIN,
            CONTENT_WIDTH,
            PAGE_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN,
            id="main",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates([PageTemplate(id="manual", frames=[frame], onPage=self.draw_page)])

    @staticmethod
    def draw_page(canvas: Canvas, doc: BaseDocTemplate) -> None:
        page = canvas.getPageNumber()
        canvas.saveState()
        if page == 1:
            canvas.setFillColor(PALE_BLUE)
            canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
            canvas.setFillColor(BLUE)
            canvas.rect(0, PAGE_HEIGHT - 7 * mm, PAGE_WIDTH, 7 * mm, stroke=0, fill=1)
            canvas.rect(0, 0, PAGE_WIDTH, 5 * mm, stroke=0, fill=1)
        else:
            canvas.setFont("CNRegular", 8)
            canvas.setFillColor(SLATE)
            canvas.drawString(LEFT_MARGIN, PAGE_HEIGHT - 10 * mm, "新DC篇完整修改器 3.0")
            canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 10 * mm, "图文使用说明")
            canvas.setStrokeColor(LINE)
            canvas.setLineWidth(0.45)
            canvas.line(LEFT_MARGIN, PAGE_HEIGHT - 12 * mm, PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 12 * mm)
            canvas.line(LEFT_MARGIN, 13 * mm, PAGE_WIDTH - RIGHT_MARGIN, 13 * mm)
            canvas.setFont("CNRegular", 7.8)
            canvas.drawString(LEFT_MARGIN, 9 * mm, "适用：DC_kuorong_464K.nes / DC_kuorong.nes")
            canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 9 * mm, f"第 {page} 页")
        canvas.restoreState()

    def afterFlowable(self, flowable: object) -> None:
        if not hasattr(flowable, "_toc_level"):
            return
        level = flowable._toc_level  # type: ignore[attr-defined]
        text = flowable._toc_text  # type: ignore[attr-defined]
        bookmark = flowable._bookmark_name  # type: ignore[attr-defined]
        self.canv.bookmarkPage(bookmark)
        self.canv.addOutlineEntry(text, bookmark, level=level, closed=False)
        self.notify("TOCEntry", (level, text, self.page, bookmark))


def build_pdf(source_path: Path, output_path: Path) -> None:
    register_fonts()
    styles = make_styles()
    source = source_path.read_text(encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    overview = ROOT / "docs" / "images" / "dc_modifier" / "12-project-overview.png"
    if not overview.exists():
        raise FileNotFoundError(f"封面图片不存在：{overview}")

    story: list[object] = [
        Spacer(1, 18 * mm),
        Paragraph("新DC篇完整修改器", styles["cover_title"]),
        Paragraph("3.0 图文使用说明", styles["cover_subtitle"]),
        Paragraph(
            "扩容版《第二次机器人大战》新 DC 篇 ROM 的完整编辑、验证与输出指南",
            styles["cover_lead"],
        ),
        Spacer(1, 6 * mm),
    ]
    features = [
        ["地图与部署", "机体 / 人物 / 武器", "剧情 / 事件 / 劝降"],
        ["背景音乐", "CHR 图像", "464 KiB 托管资源池"],
    ]
    feature_table = Table(
        [[Paragraph(cell, styles["feature"]) for cell in row] for row in features],
        colWidths=[CONTENT_WIDTH / 3] * 3,
        rowHeights=[10 * mm, 10 * mm],
    )
    feature_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#B9D8EE")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, HexColor("#B9D8EE")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.extend(
        [
            feature_table,
            Spacer(1, 7 * mm),
            figure(overview, "工程概览：基线身份、Mapper、容量与扩展空间", styles, max_height=75 * mm),
            Spacer(1, 5 * mm),
            callout(
                "**安全原则：**页面中的“应用”只更新内存工程。正式输出前必须保存 `.dcmod`、运行完整检查，并使用新文件名构建 ROM。",
                styles,
            ),
            PageBreak(),
            Paragraph("目录", styles["toc_title"]),
            Paragraph("按章节查找功能说明；PDF 阅读器侧栏同时提供书签导航。", styles["toc_note"]),
        ]
    )
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "TOCLevel0",
            fontName="CNRegular",
            fontSize=9.5,
            leading=15,
            leftIndent=0,
            firstLineIndent=0,
            textColor=NAVY,
            spaceBefore=0.7 * mm,
        ),
        ParagraphStyle(
            "TOCLevel1",
            fontName="CNRegular",
            fontSize=8.4,
            leading=12.5,
            leftIndent=8 * mm,
            firstLineIndent=0,
            textColor=SLATE,
        ),
    ]
    story.extend([toc, PageBreak()])
    story.extend(render_markdown(source, styles))

    document = ManualDocTemplate(str(output_path))
    document.multiBuild(story)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成新DC篇完整修改器图文 PDF 使用说明")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_pdf(args.source.resolve(), args.output.resolve())
    print(args.output.resolve())


if __name__ == "__main__":
    main()
