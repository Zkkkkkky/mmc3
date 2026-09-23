from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class GuideTopic:
    title: str
    route: str
    summary: str
    steps: tuple[str, ...]
    result: str
    caution: str = ""


GUIDE_TOPICS = (
    GuideTopic(
        "第一次使用：五步完成修改",
        "open_rom",
        "不需要懂 ROM、地址或指针。先打开推荐 ROM，再按模块修改，最后另存一份新 ROM。",
        (
            "点“选择 ROM…”，建议选择 output/rom/DC_kuorong_464K.nes。",
            "从本向导选择要修改的模块。",
            "在模块里选择对象并修改；看到“暂存/应用”时先点它。",
            "独立窗口点“确定”，把本窗口的修改交回主程序。",
            "按 Ctrl+S 选择新的 .nes 文件名；不要把基准 ROM 当输出文件。",
        ),
        "得到一份可在模拟器中测试的派生 ROM；基准 ROM 保持不变。",
    ),
    GuideTopic(
        "地图、部署与商店事件",
        "maps",
        "修改地图图块、我方/敌方部署、初始配置、商店和踩点事件。",
        (
            "在顶部选择关卡。",
            "点地图图块或表格中的一行，右侧会显示可修改内容。",
            "修改后点“应用当前改动”；没有变化时按钮变灰是正常状态。",
            "回到主窗口后按 Ctrl+S 另存 ROM。",
        ),
        "地图画面、部署或事件表会写入派生 ROM。",
        "删除、增加或变长操作超过本关容量时会被整体拒绝，不会写坏相邻数据。",
    ),
    GuideTopic(
        "数据库：机体",
        "database:0",
        "修改机体名称、能力、武器、类型、图标、战斗图和碎片图。",
        (
            "在左侧搜索或选择机体。",
            "修改数值；图像请进入“机体拼图”“碎片拼图”或上传入口。",
            "点“暂存当前机体”。",
            "窗口右下角点“确定”；点“取消”会放弃本次数据库会话。",
        ),
        "机体数值和图像作为同一次数据库会话保存。",
        "“添加”显示的是容量说明：编号已经到 $FF；替换现有 ID 请使用复制/粘贴或导入。",
    ),
    GuideTopic(
        "数据库：人物与头像",
        "database:1",
        "修改人物名称、音乐、精神、成长、修正值、台词和头像，并导出三张头像 BMP。",
        (
            "在左侧选择人物。",
            "在属性、精神、头像或台词页修改内容。",
            "导出头像时选择目录，会生成 [正面].bmp、[背面].bmp、[效果].bmp。",
            "点“暂存当前人物”，最后点右下角“确定”。",
        ),
        "人物数据或头像进入当前工程；之后 Ctrl+S 另存 ROM。",
        "共享记录会列出所有受影响人物并要求再次确认；不确定时选“取消”。",
    ),
    GuideTopic(
        "数据库：武器与动画测试",
        "database:2",
        "修改武器名称、威力、射程、命中、特技和敌我动画参数，并可生成隔离测试战场。",
        (
            "在左侧选择武器。",
            "修改基本属性，或在敌我动画页调整允许编辑的参数。",
            "点“暂存当前武器”。需要实战时再点“动画测试”。",
            "数据库窗口点“确定”，主窗口再 Ctrl+S。",
        ),
        "武器属性与安全动画参数写入派生 ROM；动画测试不会覆盖原 ROM 或原存档。",
        "规律代码和未验证指针保持只读；规律名称可保存到 .dcmod 工程。",
    ),
    GuideTopic(
        "数据库：战斗对话",
        "database:3",
        "修改人物之间的战斗对话，并处理同一条对话的随机分支。",
        (
            "先在左侧选记录，再选随机分支。",
            "编辑文字后点“暂存文字修改”。",
            "继续修改其他对话，或直接点右下角“确定”。",
            "回到主窗口后按 Ctrl+S 另存 ROM。",
        ),
        "战斗对话作为数据库会话的一部分统一确认或取消。",
        "文字池有固定容量；超出时会保留输入并提示需要缩短哪一类文字。",
    ),
    GuideTopic(
        "数据库：经验、成长与系统文字",
        "database:4",
        "修改命中阈值、经验、人物成长表和系统文字。",
        (
            "选择“命中/经验”“成长”或“系统文字”子页。",
            "选择记录并修改允许编辑的数值或文字。",
            "点当前页的暂存/应用按钮。",
            "完成后点数据库右下角“确定”，再按 Ctrl+S。",
        ),
        "合法字段进入当前工程；所有数据库页仍可一次确认或一次取消。",
        "等级结构上限和固定文字池不会自动扩张；点击容量说明可查看原因。",
    ),
    GuideTopic(
        "数据库：道具与商店",
        "database:5",
        "修改道具名称、价格、说明，以及有效商店的商品、店员和对话。",
        (
            "在左侧道具表或右侧商店表选择一行。",
            "修改名称、价格、说明或商店设置。",
            "检查页面提示；无效商店会保持只读并说明原因。",
            "点数据库右下角“确定”，再按 Ctrl+S。",
        ),
        "道具与有效商店字段进入当前工程。",
        "价格必须能被 10 整除；F5—FE 指向事件表，不能当普通商店写入。",
    ),
    GuideTopic(
        "剧情、关卡事件与行动",
        "scenario",
        "修改剧情文字、关卡标题、胜利文字、界面/回合/即时事件、行动和劝降条件。",
        (
            "在左侧选择关卡。",
            "选择上方页签；事件列表可双击，也可点“编辑所选事件指令…”。",
            "只改看得懂的字段；原码编辑会检查指令长度和结构。",
            "点窗口“确定”，再从主窗口保存派生 ROM。",
        ),
        "合法草稿会一次提交；任一草稿有错误时整个窗口不会提交。",
        "先使用底部“检查剩余空间”，可以在保存前发现容量不足。",
    ),
    GuideTopic(
        "字库与文字显示",
        "font",
        "修改 12×12 中文字模、导入/导出字库页，并可为新字符分配安全编码。",
        (
            "选择文字页和字符。",
            "在点阵中左键绘制、右键擦除。",
            "点阵变化后“写入文字”才会启用。",
            "最后点“确定”，再保存工程或派生 ROM。",
        ),
        "字模变化写入当前工程；无变化时按钮灰色不代表功能缺失。",
    ),
    GuideTopic(
        "地图动画与规律",
        "animation",
        "修改地图动画的颜色、等待、图库、坐标、声音、循环及已验证调用。",
        (
            "在动画页选择动画和指令。",
            "下方出现参数时直接修改；“代码编辑”可按现有指针定位并展开安全代码。",
            "规律页可改已验证参数；调用页只有有证据的位置能选择新动画。",
            "点“确定”把整个窗口作为一次修改提交。",
        ),
        "允许的参数、复制和调用修改可撤销；未知控制码不会被写入。",
        "灰色调用表示上下文证据不足，不是让初学者自行猜地址。",
    ),
    GuideTopic(
        "文字转换工具",
        "converter",
        "在普通文字、修改器代码和十六进制字节之间转换，不直接修改 ROM。",
        (
            "把文字或代码粘贴到对应输入框。",
            "选择需要的转换方向。",
            "复制结果到需要编辑文字的模块。",
        ),
        "这是辅助工具；关闭窗口不会产生 ROM 改动。",
    ),
    GuideTopic(
        "属性计算器",
        "calculator",
        "按当前 ROM 的人物、机体、武器和等级计算双方属性与伤害。",
        (
            "分别选择敌方和我方人物、机体、等级与武器。",
            "需要临时倍率时点“更改倍数”。",
            "查看结果；重新选择会立即重新计算。",
        ),
        "计算器只读取当前工程；倍率和计算结果不会写入 ROM。",
    ),
    GuideTopic(
        "存档修改器",
        "save",
        "编辑独立的 .sav 存档，包括队伍和活动战场，不要求先打开 ROM。",
        (
            "点“打开存档文件”。",
            "点“读取存档”，选择槽位并修改表格。",
            "点“写入存档”，再点“保存存档文件”。",
            "保留自动生成的备份文件，先在模拟器中验证。",
        ),
        "修改保存到所选 .sav；打开 ROM 后还能显示更友好的人物和机体名称。",
    ),
    GuideTopic(
        "战斗背景音乐",
        "music",
        "修改人物或机体使用的战斗音乐，并管理扩展曲目。",
        (
            "选择音乐或绑定对象。",
            "试听或核对曲目名称，再修改绑定。",
            "点页内应用，最后点窗口“确定”。",
        ),
        "音乐绑定进入当前工程；扩展曲仍受 Bank 容量和构建检查保护。",
    ),
    GuideTopic(
        "机体包导入与 CHR 图像",
        "unit_import",
        "把已有机体复制到另一个 ID，或导入受支持的 .dcunit 数据包和图像。",
        (
            "选择来源机体或打开 .dcunit 文件。",
            "选择要替换的目标机体 ID。",
            "先阅读“影响范围”，确认共享记录和图块使用者。",
            "点应用，最后点窗口“确定”。",
        ),
        "受支持资源会作为一次事务保存；不完整数据包会在写入前拒绝。",
    ),
    GuideTopic(
        "扩展容量规划",
        "resources",
        "查看各类资源还剩多少空间，并在大型导入前规划安全区域。",
        (
            "先阅读当前容量和推荐规划。",
            "只有确实需要扩展时才应用规划。",
            "规划后到“变更与验证”检查冲突。",
            "任何容量不足提示都应先取消，不要反复强行保存。",
        ),
        "合法规划会写入工程元数据和扩展区；受保护 Bank 不会被分配。",
    ),
    GuideTopic(
        "最终检查与导出",
        "changes",
        "保存前查看改了什么，执行完整检查，再生成派生 ROM 或 IPS。",
        (
            "打开“变更与验证”，检查变更列表是否符合预期。",
            "按 F7 执行完整检查，先处理所有错误。",
            "按 Ctrl+S 另存派生 ROM；需要分享时优先导出 IPS。",
            "用 Mesen 实际进入被修改的关卡或功能复验。",
        ),
        "形成可测试的 ROM/IPS；原始基准 ROM 不会被覆盖。",
        "不要发布受版权保护的完整 ROM；优先分发补丁和说明。",
    ),
)


class BeginnerGuideDialog(QDialog):
    route_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, has_project: bool) -> None:
        super().__init__(parent)
        self.has_project = has_project
        self.setWindowTitle("新手操作向导")
        self.resize(920, 650)

        root = QVBoxLayout(self)
        heading = QLabel("不用理解 ROM 地址：选择左侧任务，照着步骤操作")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)

        body = QHBoxLayout()
        self.topic_list = QListWidget()
        self.topic_list.setMinimumWidth(275)
        self.topic_list.addItems(topic.title for topic in GUIDE_TOPICS)
        body.addWidget(self.topic_list, 1)

        detail = QVBoxLayout()
        self.content = QTextBrowser()
        self.content.setOpenExternalLinks(False)
        detail.addWidget(self.content, 1)
        self.open_button = QPushButton("打开这个功能")
        self.open_button.clicked.connect(self._open_current)
        detail.addWidget(self.open_button)
        body.addLayout(detail, 3)
        root.addLayout(body, 1)

        close_button = QPushButton("关闭向导")
        close_button.clicked.connect(self.reject)
        root.addWidget(close_button)

        self.topic_list.currentRowChanged.connect(self._show_topic)
        self.topic_list.setCurrentRow(0)

    def _show_topic(self, row: int) -> None:
        if not 0 <= row < len(GUIDE_TOPICS):
            return
        topic = GUIDE_TOPICS[row]
        steps = "".join(
            f"<li style='margin-bottom:8px'>{escape(step)}</li>"
            for step in topic.steps
        )
        caution = (
            f"<p><b>需要注意：</b>{escape(topic.caution)}</p>"
            if topic.caution
            else ""
        )
        self.content.setHtml(
            f"<h2>{escape(topic.title)}</h2>"
            f"<p style='font-size:15px'>{escape(topic.summary)}</p>"
            f"<h3>按这个顺序操作</h3><ol>{steps}</ol>"
            f"<p><b>完成后：</b>{escape(topic.result)}</p>{caution}"
            "<hr><p><b>统一规则：</b>页内“暂存/应用”只把当前表单交给窗口；"
            "窗口“确定”交给主程序；主窗口 Ctrl+S 才会写出派生 ROM。"
            "“取消”用于放弃当前窗口尚未确认的修改。</p>"
        )
        available = self.has_project or topic.route in {"open_rom", "save"}
        self.open_button.setEnabled(available)
        self.open_button.setText(
            "打开这个功能" if available else "请先打开 ROM"
        )

    def _open_current(self) -> None:
        row = self.topic_list.currentRow()
        if not 0 <= row < len(GUIDE_TOPICS):
            return
        topic = GUIDE_TOPICS[row]
        if not self.has_project and topic.route not in {"open_rom", "save"}:
            return
        self.route_requested.emit(topic.route)
        self.accept()
