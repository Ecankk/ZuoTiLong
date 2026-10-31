from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class HtmlNode:
    def __init__(self, tag: str, attrs: dict[str, str] | None = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[HtmlNode | str] = []

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())


class TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(HtmlNode(tag, {key: value or "" for key, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def parse_html_fragment(source: str) -> HtmlNode:
    parser = TreeParser()
    parser.feed(source)
    parser.close()
    return parser.root


def descendants(node: HtmlNode, *, tag: str | None = None, class_name: str | None = None) -> Iterable[HtmlNode]:
    for child in node.children:
        if not isinstance(child, HtmlNode):
            continue
        if (tag is None or child.tag == tag) and (class_name is None or class_name in child.classes):
            yield child
        yield from descendants(child, tag=tag, class_name=class_name)


def first_descendant(node: HtmlNode, *, tag: str | None = None, class_name: str | None = None) -> HtmlNode | None:
    return next(descendants(node, tag=tag, class_name=class_name), None)


def node_text(node: HtmlNode | None, *, skip_class: str | None = None) -> str:
    if node is None:
        return ""
    pieces: list[str] = []

    def visit(item: HtmlNode | str) -> None:
        if isinstance(item, str):
            pieces.append(item)
            return
        if skip_class and skip_class in item.classes:
            return
        if item.tag in {"br", "hr"}:
            pieces.append("\n")
            return
        if item.tag in {"div", "p", "li"} and pieces and not pieces[-1].endswith("\n"):
            pieces.append("\n")
        for child in item.children:
            visit(child)
        if item.tag in {"div", "p", "li"}:
            pieces.append("\n")

    visit(node)
    text = "".join(pieces).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def require_revision(revision: str) -> str:
    normalized = revision.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{7,40}|test-fixture", normalized):
        raise ValueError("source revision must be a Git SHA (7-40 hex characters)")
    return normalized
