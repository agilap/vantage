from html.parser import HTMLParser
import html
import re
from pathlib import Path


class _TextExtractor(HTMLParser):
    """Minimal HTML parser that collects visible text only."""

    SKIP_TAGS = {"script", "style", "head", "meta", "link", "noscript"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str):
        if tag.lower() in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str):
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def parse_htm(file_path: str) -> dict:
    """Parse an HTML/HTM file and return plain text in PDF-compatible format."""
    try:
        path = Path(file_path)
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = path.read_text(encoding="latin-1")

        parser = _TextExtractor()
        parser.feed(raw)
        text = html.unescape(parser.get_text())

        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if len(line) > 2]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return {
            "text": text,
            "page_count": 1,
            "metadata": {
                "filename": path.name,
                "parse_method": "htm_strip",
                "file_type": "htm",
            },
            "error": None,
        }
    except Exception as exc:
        return {"text": "", "page_count": 0, "metadata": {}, "error": str(exc)}
