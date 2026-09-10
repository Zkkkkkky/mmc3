from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

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

    def encode_preserving_tokens(self, source_raw: bytes, edited_text: str) -> bytes:
        """Encode an edit while retaining every unchanged source token byte.

        Some glyphs have multiple byte aliases.  Decoding and then encoding a
        whole string would select one canonical alias and rewrite unrelated
        bytes.  Equal Unicode spans are therefore mapped back to their complete
        original tokens; only changed spans use the normal encoder.
        """

        source_text = self.decode(source_raw)
        if edited_text == source_text:
            return source_raw

        token_spans: list[tuple[int, int, bytes]] = []
        text_cursor = 0
        for token in StoryTextCodec.tokenize(source_raw):
            token_text = self.byte_to_text.get(
                token.raw,
                f"<{token.raw.hex().upper()}>",
            )
            token_end = text_cursor + len(token_text)
            token_spans.append((text_cursor, token_end, token.raw))
            text_cursor = token_end
        if text_cursor != len(source_text):
            return self.encode(edited_text)

        preserved: list[tuple[int, int, bytes]] = []
        matcher = SequenceMatcher(None, source_text, edited_text, autojunk=False)
        for tag, source_start, source_end, edited_start, _edited_end in matcher.get_opcodes():
            if tag != "equal":
                continue
            for token_start, token_end, raw in token_spans:
                if source_start <= token_start and token_end <= source_end:
                    preserved.append(
                        (
                            edited_start + token_start - source_start,
                            edited_start + token_end - source_start,
                            raw,
                        )
                    )

        result = bytearray()
        edited_cursor = 0
        for token_start, token_end, raw in preserved:
            if token_start < edited_cursor:
                continue
            result.extend(self.encode(edited_text[edited_cursor:token_start]))
            result.extend(raw)
            edited_cursor = token_end
        result.extend(self.encode(edited_text[edited_cursor:]))
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
