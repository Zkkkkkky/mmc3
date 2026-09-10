from __future__ import annotations

from dataclasses import dataclass

from .codecs.story_text import StoryTextCodec


@dataclass(frozen=True)
class TextTable:
    byte_to_text: dict[bytes, str]

    def __post_init__(self) -> None:
        if any(not key or not value for key, value in self.byte_to_text.items()):
            raise ValueError("字库映射的编码和值不能为空。")

    @classmethod
    def parse(cls, text: str) -> "TextTable":
        mapping: dict[bytes, str] = {}
        for line_number, source_line in enumerate(text.splitlines(), 1):
            if not source_line.strip() or source_line.lstrip().startswith(("#", ";")):
                continue
            line = source_line
            if "=" not in line:
                raise ValueError(f"字库表第 {line_number} 行缺少等号。")
            code_text, value_text = line.split("=", 1)
            compact = "".join(code_text.split())
            if not compact or len(compact) % 2:
                raise ValueError(f"字库表第 {line_number} 行编码无效。")
            try:
                code = bytes.fromhex(compact)
            except ValueError as error:
                raise ValueError(f"字库表第 {line_number} 行含无效十六进制。") from error
            value = (
                value_text.replace(r"\n", "\n")
                .replace(r"\r", "\r")
                .replace(r"\t", "\t")
            )
            if not value:
                continue
            if code in mapping:
                raise ValueError(f"字库表第 {line_number} 行编码重复。")
            mapping[code] = value
        if not mapping:
            raise ValueError("字库表没有有效映射。")
        return cls(mapping)

    @property
    def text_to_byte(self) -> dict[str, bytes]:
        # The shipped DC font contains duplicate glyphs in several banks and
        # also has compact one-byte punctuation aliases. Prefer the shortest
        # code so an unchanged Unicode edit cannot grow merely because a
        # two-byte duplicate appeared earlier in the source table.
        reverse: dict[str, bytes] = {}
        for key, value in sorted(
            self.byte_to_text.items(), key=lambda item: len(item[0])
        ):
            reverse.setdefault(value, key)
        return reverse

    def decode(self, raw: bytes) -> str:
        result: list[str] = []
        for token in StoryTextCodec.tokenize(raw):
            result.append(self.byte_to_text.get(token.raw, f"<{token.raw.hex().upper()}>"))
        return "".join(result)

    def encode(self, text: str) -> bytes:
        reverse = self.text_to_byte
        values = sorted(reverse, key=len, reverse=True)
        result = bytearray()
        cursor = 0
        while cursor < len(text):
            if text[cursor] == "<":
                close = text.find(">", cursor + 1)
                if close >= 0:
                    compact = "".join(text[cursor + 1 : close].split())
                    if compact and len(compact) % 2 == 0:
                        try:
                            result.extend(bytes.fromhex(compact))
                            cursor = close + 1
                            continue
                        except ValueError:
                            pass
            match = next(
                (value for value in values if text.startswith(value, cursor)),
                None,
            )
            if match is None:
                excerpt = text[cursor : cursor + 8].replace("\n", r"\n")
                raise ValueError(f"文字“{excerpt}”没有字库编码。")
            result.extend(reverse[match])
            cursor += len(match)
        return bytes(result)

    @staticmethod
    def template(tokens: set[bytes]) -> str:
        rows = [
            "# 新DC剧情字库表：在等号右侧填写字符或控制码名称。",
            r"# 示例：C901=机　FF=[结束]　F0=\n",
        ]
        rows.extend(
            f"{token.hex().upper()}="
            for token in sorted(tokens, key=lambda item: (len(item), item))
        )
        return "\n".join(rows) + "\n"
