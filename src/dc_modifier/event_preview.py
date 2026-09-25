from __future__ import annotations

from collections.abc import Callable, Mapping

from fc_editor.codecs.chapter_event import ACTION_FIELDS, OPCODE_LABELS


EVENT_MUSIC_LABELS = (
    "大卫音乐", "盖塔音乐", "加代音乐", "古莲音乐", "吉尔变身音乐",
    "安东音乐", "未知音乐2", "地球我方音乐", "地球敌方音乐", "存档音乐",
    "敌方增援音乐2", "游戏结束音乐", "宇宙我方音乐", "敌方增援音乐1",
    "升级音乐", "吉尔音乐", "瓦尔音乐", "宇宙敌方音乐", "未知音乐1",
    "通关音乐",
)


def _character(project, value: int) -> str:
    if project is None:
        return f"人物{value:03d}"
    return project.character_display_name(value)


def _unit(project, value: int) -> str:
    if project is None or value == 0:
        return f"机体{value:03d}"
    try:
        return project.unit_display_name(value)
    except (AttributeError, IndexError, ValueError):
        return f"机体{value:03d}"


def _music(value: int) -> str:
    index = value - 0x81
    return EVENT_MUSIC_LABELS[index] if 0 <= index < len(EVENT_MUSIC_LABELS) else f"音乐{value:02X}"


def reference_event_preview(
    instruction,
    *,
    index: int | None = None,
    project=None,
    address_rows: Mapping[int, int] | None = None,
    story_summary: Callable[[object], str] | None = None,
) -> str:
    """Render an event line in the terse natural-language style of the legacy UI."""

    raw = bytes(instruction.raw)
    opcode = raw[0] & 0x7F
    values = raw[1:]
    end = bool(raw[0] & 0x80)
    prefix = f"{index:03d}: " if index is not None else ""
    if raw == b"\xDF":
        return prefix + "事件结束"

    def value(position: int, default: int = 0) -> int:
        return values[position] if position < len(values) else default

    def word(position: int = 0) -> int:
        return value(position) | (value(position + 1) << 8)

    if opcode == 0x00:
        text = f"判断：第{value(0)}回合？"
    elif opcode in (0x01, 0x51, 0x52):
        switch = value(0)
        scope = "全局" if switch & 0x80 else "关卡"
        number = switch & 0x7F
        if opcode == 0x01:
            text = f"判断：{scope}开关{number}打开？"
        else:
            text = f"{'打开' if opcode == 0x51 else '关闭'}{scope}开关{number}"
    elif opcode in (0x03, 0x04, 0x05):
        place = {0x03: "队伍中", 0x04: "战场中", 0x05: "母舰中"}[opcode]
        text = f"判断：{_character(project, value(0))}在{place}？"
    elif opcode in (0x06, 0x07):
        text = f"判断：{'敌方' if opcode == 0x06 else '我方'}机体数量为{value(0)}？"
    elif opcode == 0x08:
        text = f"判断：持有道具{value(0):02X}？"
    elif opcode == 0x0A:
        text = f"判断：金钱达到{word()}？"
    elif opcode == 0x0C:
        text = f"判断：{_character(project, value(0))}到达坐标 X:{value(1)} Y:{value(2)}？"
    elif opcode in (0x0F, 0x18, 0x19, 0x46, 0x65):
        lead = {0x0F: "判断：进入坐标", 0x18: "移动到坐标", 0x19: "强制移动到坐标", 0x46: "设定光标位置：坐标", 0x65: "传送到坐标"}[opcode]
        text = f"{lead}：X:{value(0)} Y:{value(1)}"
    elif opcode == 0x10:
        text = f"判断：{_character(project, value(0))}进入范围 X:{value(1)} Y:{value(2)} 范围:{value(3)}？"
    elif opcode == 0x13:
        text = f"判断：{_character(project, value(0))}{'击落' if value(1) else '攻击'}目标？"
    elif opcode in (0x15, 0x16, 0x36, 0x38, 0x47, 0x48, 0x53, 0x54, 0x64):
        verb = {
            0x15: "向人物移动", 0x16: "强制向人物移动", 0x36: "强制移动人物",
            0x38: "传送到人物周围", 0x47: "光标移到人物", 0x48: "光标移到人物并等待",
            0x53: "设置人物移动限制", 0x54: "取消人物移动限制", 0x64: "控制人物行动",
        }[opcode]
        text = f"{verb}：{_character(project, value(0))}"
    elif opcode == 0x1E:
        text = f"控制行动（无光标）：{_character(project, value(0))}"
    elif opcode in (0x20, 0x31, 0x32, 0x33):
        text = f"{'判断剩余HP' if opcode == 0x20 else '增减HP'}：{word()}"
    elif opcode in (0x26, 0x27):
        choice = max(1, value(0) >> 4) if opcode == 0x27 else max(1, value(0))
        text = f"判断：选项 {choice} 被选择？"
    elif opcode == 0x30:
        text = f"播放战场动画：{value(0)}"
    elif opcode == 0x34:
        text = f"恢复HP：{value(0)}%"
    elif opcode == 0x39:
        text = f"恢复精神：{value(0)}"
    elif opcode == 0x3B:
        text = f"敌方精神：{value(0)}"
    elif opcode == 0x3C:
        text = f"选项事件（需要配合选项判断）：选项个数:{value(0)}"
    elif opcode in (0x40, 0x41, 0x42):
        kind = {0x40: "对话（无指向", 0x41: "对话（指向人物", 0x42: "对话调用"}[opcode]
        ending = ",结束）" if end else "）"
        story = story_summary(instruction) if story_summary is not None else ""
        portrait = "???" if opcode == 0x42 else f"{value(0):03d}"
        text = f"{kind}{ending}：头像:{portrait}，内容:{story or '???'}"
    elif opcode == 0x43:
        text = "显示文字窗口"
    elif opcode == 0x44:
        story = story_summary(instruction) if story_summary is not None else ""
        text = f"文字显示：内容:{story or '???'}"
    elif opcode == 0x45:
        text = "关闭窗口"
    elif opcode in (0x4A, 0x4B):
        side = "客军增援" if opcode == 0x4A else "敌军增援"
        text = (
            f"{side}：坐标 X:{value(0)} Y:{value(1)}，"
            f"{_character(project, value(2))}，{_unit(project, value(3))}，等级:{value(4)}"
        )
    elif opcode == 0x4C:
        text = f"我方出击/加入：坐标 X:{value(0)} Y:{value(1)}，队伍槽:{value(2)}"
    elif opcode == 0x4D:
        text = f"更换人物和机体：{_character(project, value(0))} → {_character(project, value(1))} / {_unit(project, value(2))}"
    elif opcode == 0x4E:
        text = f"更换机体：{_character(project, value(0))} → {_unit(project, value(1))}"
    elif opcode == 0x4F:
        text = f"增加或减少道具：道具{value(0):02X}，数量:{value(1)}"
    elif opcode == 0x50:
        text = f"增加或减少金钱：{word()}"
    elif opcode in (0x55, 0x56, 0x57, 0x58):
        target = word()
        row = address_rows.get(target) if address_rows is not None else None
        destination = f"{row:03d}" if row is not None else f"{target:03d}"
        lead = {0x55: "转", 0x56: "重复", 0x57: "是：转", 0x58: "否：转"}[opcode]
        text = f"{lead}：{destination}"
    elif opcode in (0x59, 0x5A, 0x5B):
        lead = {0x59: "播放我方地图音乐", 0x5A: "播放敌方地图音乐", 0x5B: "播放音乐"}[opcode]
        text = f"{lead}：{_music(value(0))}"
    elif opcode == 0x5C:
        text = f"置属性地址：{word():04X}+0 的值为{value(2)}"
    elif opcode == 0x5D:
        text = f"置双字节属性地址：{word():04X} 的值为{value(2) | (value(3) << 8)}"
    elif opcode == 0x5E:
        text = f"等待：{value(0)}帧"
    elif opcode == 0x66:
        text = f"临时更换机体：{_unit(project, value(0))}"
    elif opcode == 0x67:
        text = "更换为客军"
    elif opcode == 0x68:
        text = "更换为敌军"
    elif opcode == 0x69:
        text = "更换为我方队员"
    elif opcode == 0x6A:
        text = "自爆"
    elif opcode == 0x6B:
        text = "撤退/离场"
    elif opcode == 0x6E:
        text = f"队友离队：{_character(project, value(0))}"
    elif opcode == 0x6F:
        text = f"人物加入队伍：{_character(project, value(0))} / {_unit(project, value(1))} / 等级:{value(2)}"
    elif opcode in (0x71, 0x72, 0x73):
        text = {0x71: "关卡胜利", 0x72: "关卡失败", 0x73: "游戏通关"}[opcode]
    else:
        labels = ACTION_FIELDS.get(opcode, ())
        parameters = "，".join(
            f"{label}:{item}" for label, item in zip(labels, values)
        ) or " ".join(f"{item:02X}" for item in values)
        text = OPCODE_LABELS.get(opcode, f"事件指令{opcode:02X}")
        if parameters:
            text += f"：{parameters}"
    if end and opcode not in (0x40, 0x41, 0x42):
        text += "（结束）"
    return prefix + text
