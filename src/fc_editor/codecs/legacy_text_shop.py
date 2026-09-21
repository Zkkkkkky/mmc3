from __future__ import annotations

from dataclasses import dataclass

from ..errors import RomFormatError


@dataclass(frozen=True)
class LegacyShopRecord:
    shop_id: int
    file_offset: int
    clerk_id: int
    dialogue_id: int
    items: tuple[int, ...]
    raw: bytes


class LegacyShopCodec:
    POINTER_TABLE = 0x15753
    EXPECTED_POINTERS = (0x9763, 0x976B, 0x9773, 0x977B, 0x9783) + (0x987E,) * 10
    LABELS = ("进入商店", "准备购买", "金钱不够", "数量超限", "是否购买", "购买之后", "离开商店")

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = bytes(data)
        pointers = tuple(int.from_bytes(self.data[self.POINTER_TABLE + index * 2:self.POINTER_TABLE + index * 2 + 2], "little") for index in range(15))
        if pointers != self.EXPECTED_POINTERS:
            raise RomFormatError("商店目录的指针表与已验证布局不匹配。")
        for shop_id in range(0xF0, 0xF5):
            self.record(shop_id)

    def record(self, shop_id: int) -> LegacyShopRecord:
        if not 0xF0 <= shop_id <= 0xFE:
            raise ValueError("商店编号须在 F0—FE 之间。")
        if shop_id >= 0xF5:
            raise ValueError("此目录指向地图事件指针表，并非有效商店记录。")
        offset = 0xC010 + self.EXPECTED_POINTERS[shop_id - 0xF0]
        clerk, window, dialogue, count = self.data[offset:offset + 4]
        capacity = 4 if shop_id < 0xF4 else 1
        if window != 0x0F or count != capacity or clerk > 0xC7 or dialogue + 6 >= 221:
            raise RomFormatError("商店记录的店员、窗口、对话或商品数量无效。")
        raw = self.data[offset:offset + 4 + count]
        if len(raw) != 4 + count or any(value >= 24 for value in raw[4:]):
            raise RomFormatError("商店商品编号超出道具表。")
        return LegacyShopRecord(shop_id, offset, clerk, dialogue, tuple(value + 1 for value in raw[4:]), raw)

    def replacement_patch(self, shop_id: int, clerk_id: int, dialogue_id: int, items) -> tuple[int, bytes, bytes]:
        record = self.record(shop_id)
        items = tuple(items)
        if not 0 <= clerk_id <= 0xC7 or not 0 <= dialogue_id <= 214:
            raise ValueError("店员须在 00—C7，对话起始编号须在 0—214 之间。")
        if len(items) != len(record.items) or any(not 1 <= value <= 24 for value in items):
            raise ValueError(f"此商店须保持 {len(record.items)} 件商品，每件编号须在 1—24 之间。")
        after = bytes((clerk_id, record.raw[1], dialogue_id, len(items), *(value - 1 for value in items)))
        return record.file_offset, record.raw, after
