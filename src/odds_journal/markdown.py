from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import MatchMetadata


SECTION_NAMES = (
    "prematch-facts",
    "prematch-reasoning",
    "prematch-locked",
    "live-update",
    "result",
    "postmatch-review",
)
PREMATCH_SECTIONS = SECTION_NAMES[:3]
MARKER_RE = re.compile(r"<!-- section:([a-z-]+) -->")
FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
IMAGE_RE = re.compile(r"!\[[^]]*]\(([^)]+)\)")


class DocumentError(ValueError):
    pass


@dataclass
class MatchDocument:
    path: Path
    metadata: MatchMetadata
    body: str
    prefix: str
    sections: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> "MatchDocument":
        text = path.read_text(encoding="utf-8")
        front = FRONT_MATTER_RE.match(text)
        if not front:
            raise DocumentError("缺少 YAML Front Matter")
        raw = yaml.safe_load(front.group(1)) or {}
        try:
            metadata = MatchMetadata.model_validate(raw)
        except Exception as exc:
            raise DocumentError(str(exc)) from exc
        body = text[front.end() :]
        prefix, sections = parse_sections(body)
        return cls(path=path, metadata=metadata, body=body, prefix=prefix, sections=sections)

    def save(self) -> None:
        raw = self.metadata.model_dump(mode="json")
        header = yaml.safe_dump(
            raw,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).rstrip()
        self.path.write_text(f"---\n{header}\n---\n{self.body}", encoding="utf-8", newline="\n")

    def replace_section(self, name: str, content: str) -> None:
        if name not in SECTION_NAMES:
            raise DocumentError(f"未知章节：{name}")
        self.sections[name] = content.strip("\n") + "\n"
        self.body = render_sections(self.prefix, self.sections)

    def prematch_hash(self) -> str:
        blocks = []
        for name in PREMATCH_SECTIONS:
            content = self.sections[name].replace("\r\n", "\n").replace("\r", "\n")
            blocks.append(content.rstrip("\n") + "\n")
        return hashlib.sha256("".join(blocks).encode("utf-8")).hexdigest()

    def broken_images(self) -> list[str]:
        missing: list[str] = []
        for target in IMAGE_RE.findall(self.body):
            if re.match(r"^[a-z]+://", target, re.I):
                continue
            clean = target.split("#", 1)[0].split("?", 1)[0]
            if clean and not (self.path.parent / clean).exists():
                missing.append(target)
        return missing


def parse_sections(body: str) -> tuple[str, dict[str, str]]:
    matches = list(MARKER_RE.finditer(body))
    found = [match.group(1) for match in matches]
    if found != list(SECTION_NAMES):
        raise DocumentError(f"章节标记必须按固定顺序且各出现一次；当前为 {found}")
    prefix = body[: matches[0].start()]
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1)] = body[match.end() : end].lstrip("\r\n")
    return prefix, sections


def render_sections(prefix: str, sections: dict[str, str]) -> str:
    output = [prefix.rstrip("\n") + "\n\n"]
    for name in SECTION_NAMES:
        output.append(f"<!-- section:{name} -->\n")
        output.append(sections[name].rstrip("\n") + "\n\n")
    return "".join(output).rstrip() + "\n"


def has_substantive_content(content: str, minimum: int = 12) -> bool:
    meaningful: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        if re.fullmatch(r"[-|: ]+", stripped):
            continue
        if re.fullmatch(r"[-*]\s*[^：:]+[：:]\s*", stripped):
            continue
        meaningful.append(stripped)
    return len("".join(meaningful)) >= minimum


def metadata_to_yaml(metadata: MatchMetadata) -> str:
    return yaml.safe_dump(
        metadata.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()


def generic_front_matter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    front = FRONT_MATTER_RE.match(text)
    if not front:
        return {}, text
    return yaml.safe_load(front.group(1)) or {}, text[front.end() :]

