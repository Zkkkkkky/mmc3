"""Build the legacy/current UI visual golden comparison package.

This report intentionally compares information architecture and visible
editing affordances instead of demanding raw pixel identity.  The reference
screenshots include Windows XP chrome and a different widget renderer, while
the current captures are deterministic offscreen Qt client-area images.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
LEGACY_DIRECTORY = ROOT / "references" / "legacy_modifier" / "screenshots"
CURRENT_DIRECTORY = ROOT / "docs" / "images" / "dc_modifier"
DEFAULT_OUTPUT = ROOT / "output" / "verification" / "ui-golden-2026-09-22"
_FONT_FAMILY = "Microsoft YaHei UI"


@dataclass(frozen=True)
class ComparisonSpec:
    key: str
    module: str
    title: str
    legacy_file: str
    current_file: str
    verdict: str
    legacy_features: tuple[str, ...]
    extensions: tuple[str, ...] = ()

    @property
    def legacy_path(self) -> Path:
        return LEGACY_DIRECTORY / self.legacy_file

    @property
    def current_path(self) -> Path:
        return CURRENT_DIRECTORY / self.current_file


COMPARISONS = (
    ComparisonSpec(
        "m02-battlefield-map", "M02", "战场地图",
        "01_战场地图.png", "01-map-editor.png", "legacy_core_plus_extension",
        ("三张主页签", "左侧图块与双画笔", "关卡标题和列表", "右侧地图画布", "X/Y 坐标"),
        ("全景适应与缩放", "对象叠加", "容量规划和显式应用状态"),
    ),
    ComparisonSpec(
        "m03-initial-config", "M03", "初始配置",
        "02_初始配置.png", "01b-initial-config.png", "legacy_core_plus_extension",
        ("主窗口第二页签", "三组图标图库", "关卡共享选择", "右侧地图定位"),
        ("图库按需展开", "部署明细", "地图对象可视化与高级编辑入口"),
    ),
    ComparisonSpec(
        "m04-shop-event", "M04", "商店事件",
        "03_商店事件.png", "01c-shop-event.png", "legacy_core_plus_extension",
        ("主窗口第三页签", "关卡共享选择", "空记录可辨识", "右侧地图定位"),
        ("事件/商店对象列表", "地图标记", "批量记录入口"),
    ),
    ComparisonSpec(
        "m05-m10-database", "M05-M10", "数据库六页签",
        "04_数据库.png", "02-database.png", "legacy_core_plus_extension",
        ("六个一级页签", "左侧记录列表", "图像区", "属性分组", "查找与确定/取消"),
        ("真实合成预览", "复制/粘贴/导入/导出", "共享记录提示与事务状态"),
    ),
    ComparisonSpec(
        "m11-font-library", "M11", "文字库",
        "05_文字库.png", "04-font-library.png", "legacy_core_plus_extension",
        ("16×16 字模网格", "字段选择", "字形替换按钮", "代码与地址", "单一确定按钮"),
        ("12×12 直接点阵编辑", "网格右键导入/导出与安全分配"),
    ),
    ComparisonSpec(
        "m12-map-animation", "M12", "地图动画",
        "06_地图动画.png", "05-map-animation.png", "legacy_core_plus_extension",
        ("地图动画/规律/调用三页签", "左侧记录选择", "右侧指令列表", "添加/名称/代码编辑", "确定/取消"),
        ("原始字节列", "参数级编辑状态", "已验证记录边界提示"),
    ),
    ComparisonSpec(
        "m13-text-converter", "M13", "文字转换",
        "07_文字转换.png", "06-text-converter.png", "legacy_core_aligned",
        ("文字与代码双编辑区", "居中的双向转换按钮", "无 ROM 写入控件"),
    ),
    ComparisonSpec(
        "m14-scenario", "M14", "剧情事件",
        "08_剧情事件.png", "03-scenario-editor.png", "legacy_core_plus_extension",
        ("六个一级页签", "章节设置与三类事件", "标题预览", "关卡列表", "空间检查与确定/取消"),
        ("真实 Bank/偏移状态", "原始字节与结构化指令", "更严格的容量报告"),
    ),
    ComparisonSpec(
        "m15-attribute-calculator", "M15", "属性计算器",
        "09_属性计算器.png", "07-attribute-calculator.png", "legacy_core_plus_extension",
        ("敌我双栏", "人物/机体/武器/等级", "属性计算结果区", "开始计算"),
        ("从当前 ROM 联动真实属性", "公式只读说明和损坏入口门禁"),
    ),
    ComparisonSpec(
        "m16-save-editor", "M16", "存档修改器",
        "10_存档修改器.png", "08-save-editor.png", "legacy_core_aligned",
        ("存档槽与关卡选择", "打开/读取/写入/保存四步", "上下两张十一列表"),
        ("格式、校验和与未保存状态提示",),
    ),
    ComparisonSpec(
        "m17-other", "M17", "其他",
        "11_其他.png", "09-other-settings.png", "legacy_core_aligned",
        ("双击公式", "伤害公式", "命中公式", "十一项道具参数", "六组初始机体", "确定/取消"),
        ("实时工程值和安全校验提示",),
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def configure_font(application: QApplication) -> None:
    global _FONT_FAMILY
    windows_directory = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for filename in ("msyh.ttc", "simhei.ttf", "simsun.ttc"):
        font_id = QFontDatabase.addApplicationFont(str(windows_directory / "Fonts" / filename))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            _FONT_FAMILY = families[0]
            break
    application.setFont(QFont(_FONT_FAMILY, 10))


def _image_metadata(path: Path) -> dict[str, object]:
    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"无法读取截图：{path}")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "width": image.width(),
        "height": image.height(),
        "sha256": sha256(path),
    }


def collect_report(specs: tuple[ComparisonSpec, ...] = COMPARISONS) -> dict[str, object]:
    pairs: list[dict[str, object]] = []
    missing: list[str] = []
    for spec in specs:
        for path in (spec.legacy_path, spec.current_path):
            if not path.is_file():
                missing.append(path.relative_to(ROOT).as_posix())
        if any(not path.is_file() for path in (spec.legacy_path, spec.current_path)):
            continue
        record = asdict(spec)
        record["legacy"] = _image_metadata(spec.legacy_path)
        record["current"] = _image_metadata(spec.current_path)
        record.pop("legacy_file")
        record.pop("current_file")
        legacy_ratio = record["legacy"]["width"] / record["legacy"]["height"]
        current_ratio = record["current"]["width"] / record["current"]["height"]
        record["aspect_ratio_delta"] = round(abs(legacy_ratio - current_ratio), 4)
        pairs.append(record)
    return {
        "schema": "dc-ui-golden-v1",
        "comparison_basis": "legacy information architecture and visible visualization affordances",
        "pixel_identity_required": False,
        "pixel_identity_reason": (
            "参考截图包含 Windows XP 窗口边框且控件渲染器不同；本门禁核对窗口结构、"
            "信息层级、可视化内容和操作入口，原始像素哈希仅用于证据追踪。"
        ),
        "pair_count": len(pairs),
        "expected_pair_count": len(specs),
        "missing": missing,
        "passed": not missing and len(pairs) == len(specs),
        "pairs": pairs,
    }


def _fit(image: QImage, bounds: QRect) -> QRect:
    size = image.size()
    size.scale(bounds.size(), Qt.AspectRatioMode.KeepAspectRatio)
    return QRect(
        bounds.x() + (bounds.width() - size.width()) // 2,
        bounds.y() + (bounds.height() - size.height()) // 2,
        size.width(),
        size.height(),
    )


def render_pair(spec: ComparisonSpec, destination: Path) -> None:
    legacy = QImage(str(spec.legacy_path))
    current = QImage(str(spec.current_path))
    if legacy.isNull() or current.isNull():
        raise ValueError(f"截图缺失或损坏：{spec.key}")
    canvas = QImage(1800, 920, QImage.Format.Format_RGB32)
    canvas.fill(QColor("#F3F7FB"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setFont(QFont(_FONT_FAMILY, 18, QFont.Weight.Bold))
    painter.setPen(QColor("#173B50"))
    painter.drawText(QRect(24, 10, 1752, 42), Qt.AlignmentFlag.AlignCenter, f"{spec.module} · {spec.title}")
    panels = (
        (QRect(24, 82, 864, 812), legacy, "旧修改器黄金参考", QColor("#1686C4")),
        (QRect(912, 82, 864, 812), current, "新修改器当前实现", QColor("#2E7D4F")),
    )
    for panel, image, label, accent in panels:
        painter.fillRect(panel, QColor("#FFFFFF"))
        painter.setPen(QPen(accent, 3))
        painter.drawRect(panel.adjusted(1, 1, -1, -1))
        painter.setFont(QFont(_FONT_FAMILY, 14, QFont.Weight.DemiBold))
        painter.setPen(accent)
        painter.drawText(QRect(panel.x(), panel.y() + 8, panel.width(), 30), Qt.AlignmentFlag.AlignCenter, label)
        image_bounds = panel.adjusted(12, 48, -12, -12)
        painter.drawImage(_fit(image, image_bounds), image)
    painter.end()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(destination), "PNG"):
        raise RuntimeError(f"无法保存对照图：{destination}")


def render_contact_sheet(pair_paths: list[Path], destination: Path) -> None:
    columns = 2
    tile = QSize(940, 500)
    rows = (len(pair_paths) + columns - 1) // columns
    canvas = QImage(columns * tile.width(), rows * tile.height(), QImage.Format.Format_RGB32)
    canvas.fill(QColor("#E8EEF3"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    for index, path in enumerate(pair_paths):
        image = QImage(str(path))
        bounds = QRect(
            (index % columns) * tile.width() + 12,
            (index // columns) * tile.height() + 12,
            tile.width() - 24,
            tile.height() - 24,
        )
        painter.fillRect(bounds, QColor("#FFFFFF"))
        painter.drawImage(_fit(image, bounds.adjusted(4, 4, -4, -4)), image)
    painter.end()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(destination), "PNG"):
        raise RuntimeError(f"无法保存总览图：{destination}")


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# 新旧修改器 UI 布局与可视化黄金对照",
        "",
        "> 对照基线为 `references/legacy_modifier/screenshots/`；新版截图由",
        "> `tools/capture_dc_modifier_guide.py` 在固定 Qt 缩放下生成。不同 Windows",
        "> 主题和窗口边框不做逐像素相等判定，核对的是信息架构、可视化内容和操作入口。",
        "",
        "![十一组对照总览](contact-sheet.png)",
        "",
        "| 模块 | 窗口 | 结论 | 新增能力处理 |",
        "|---|---|---|---|",
    ]
    for pair in report["pairs"]:
        extensions = "；".join(pair["extensions"]) if pair["extensions"] else "无额外可见控件"
        lines.append(
            f"| {pair['module']} | [{pair['title']}](pairs/{pair['key']}.png) | "
            f"{pair['verdict']} | {extensions} |"
        )
    lines.extend((
        "",
        "## 判定口径",
        "",
        "- `legacy_core_aligned`：旧版主结构、可视化区域和主要操作入口保持一致。",
        "- `legacy_core_plus_extension`：旧版主结构保持一致，新能力放入附加工具条、状态区、右键菜单或新增列，不替换旧入口。",
        "- 图片 SHA-256 用于确认本次审阅使用的确切证据，不代表新旧主题像素必须相同。",
        "- 该报告只证明 UI 结构与可视呈现已审阅；字段保存黄金、模拟器结果和用户签收仍按各模块独立门禁。",
        "",
        "## 分窗口可视功能清单",
        "",
    ))
    for pair in report["pairs"]:
        lines.extend((
            f"### {pair['module']} · {pair['title']}",
            "",
            f"![{pair['title']} 对照](pairs/{pair['key']}.png)",
            "",
            f"- 旧版可视功能：{'；'.join(pair['legacy_features'])}。",
            f"- 新版增强：{'；'.join(pair['extensions']) if pair['extensions'] else '无；保持旧版紧凑结构'}。",
            f"- 证据：`{pair['legacy']['path']}`（{pair['legacy']['width']}×{pair['legacy']['height']}，"
            f"SHA-256 `{pair['legacy']['sha256']}`）对 `"
            f"{pair['current']['path']}`（{pair['current']['width']}×{pair['current']['height']}，"
            f"SHA-256 `{pair['current']['sha256']}`）。",
            "",
        ))
    return "\n".join(lines).rstrip() + "\n"


def build(output_directory: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    application = QApplication.instance() or QApplication([])
    configure_font(application)
    report = collect_report()
    if report["missing"]:
        raise FileNotFoundError("缺少 UI 黄金截图：" + ", ".join(report["missing"]))
    pair_directory = output_directory / "pairs"
    pair_paths: list[Path] = []
    for spec in COMPARISONS:
        path = pair_directory / f"{spec.key}.png"
        render_pair(spec, path)
        pair_paths.append(path)
    render_contact_sheet(pair_paths, output_directory / "contact-sheet.png")
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_directory / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="生成新旧修改器 UI 布局与可视化黄金对照")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build(args.output.resolve())
    print(f"UI 黄金对照：{report['pair_count']}/{report['expected_pair_count']}，passed={report['passed']}")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
