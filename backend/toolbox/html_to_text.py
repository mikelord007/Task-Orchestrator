"""Tool: convert an HTML document to readable plain text."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from ._common import err, get_int, get_str, truncate

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "div", "dd", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
    "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "tr", "ul",
}
_CELL_TAGS = {"td", "th"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
        elif tag in _CELL_TAGS:
            self._parts.append("\t")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t\r\f\v]*\n[ \t\r\f\v]*", "\n", raw)
        raw = re.sub(r"[ \t]{2,}", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


TOOL = {
    "name": "html_to_text",
    "description": (
        "Convert an HTML document into readable plain text.\n"
        "\n"
        "Returns the visible text of the page: tag markup is removed, block "
        "elements become line breaks, table cells are separated by tabs, and "
        "runs of whitespace are collapsed. Script, style, noscript, svg and "
        "head content is dropped entirely.\n"
        "\n"
        "Use this first whenever you are handed raw HTML and you want to read "
        "prose, dates, prices or headings out of it. Reading raw HTML directly "
        "wastes a large number of tokens on markup.\n"
        "\n"
        "It does NOT fetch anything from the network (pass the HTML you already "
        "have), does NOT render JavaScript, does NOT preserve the DOM structure, "
        "attributes, link hrefs or image sources, and does NOT return valid "
        "HTML. If you need an attribute value or a specific tag, use "
        "regex_extract on the original HTML instead.\n"
        "\n"
        "Arguments: 'html' is the document source. 'max_chars' (default 20000) "
        "truncates the result and marks the cut; raise it only if you know the "
        "answer sits past that point."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "html": {"type": "string", "description": "Raw HTML source to convert."},
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters of text to return. Default 20000.",
                "minimum": 1,
            },
        },
        "required": ["html"],
        "additionalProperties": False,
    },
}


def run(input: dict) -> str:
    try:
        html = get_str(input, "html")
        max_chars = get_int(input, "max_chars", required=False, default=20000, minimum=1)
    except (TypeError, ValueError) as exc:
        return err(f"html_to_text: {exc}")

    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # malformed markup should never kill a run
        return err(f"html_to_text: could not parse the HTML ({exc})")
    return truncate(parser.text(), max_chars)
