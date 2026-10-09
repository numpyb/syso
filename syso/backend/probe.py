"""Read-only probing of ISO 9660 boot equipment with xorriso.

The parsers here are written against real xorriso 1.5.8 output captured from a
hybrid (BIOS+UEFI) fixture ISO; see PLAYBOOK.md and tests/fixtures/.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import tools
from .runner import run_ok


class ProbeError(RuntimeError):
    pass


@dataclass
class ElToritoImage:
    index: int
    platform: str  # "BIOS", "UEFI", ...
    bootable: bool
    emulation: str
    load_size: int  # sectors
    path: str | None = None
    boot_info_table: bool = False
    isohybrid_suitable: bool = False


@dataclass
class MbrPartition:
    status: str
    part_type: str
    start: int
    blocks: int


@dataclass
class IsoNode:
    path: str
    name: str
    mode: str
    is_dir: bool
    is_link: bool
    size: int

    @property
    def is_binary(self) -> bool:
        return not (self.mode.startswith("d") or self.mode.startswith("l"))


@dataclass
class BootSpec:
    source: str
    iso_size: int
    volume_id: str = ""
    system_area_summary: str = ""
    el_torito_catalog: str | None = None
    images: list[ElToritoImage] = field(default_factory=list)
    mbr_partitions: list[MbrPartition] = field(default_factory=list)
    el_cmd_output: str = ""
    sys_cmd_output: str = ""

    @property
    def has_isohybrid(self) -> bool:
        return "isohybrid" in self.system_area_summary

    @property
    def has_gpt(self) -> bool:
        return "GPT" in self.system_area_summary

    @property
    def bios_image(self) -> str | None:
        for img in self.images:
            if img.platform == "BIOS" and img.path:
                return img.path
        return None

    @property
    def efi_image(self) -> str | None:
        for img in self.images:
            if img.platform == "UEFI" and img.path:
                return img.path
        return None

    @property
    def boot_info_table(self) -> bool:
        return any(i.boot_info_table for i in self.images)

    @property
    def summary(self) -> str:
        if not self.images:
            return "no El Torito boot image (plain data ISO)"
        parts = [
            f"{i.platform}@{i.path or '?'}"
            + (" [+bit]" if i.boot_info_table else "")
            for i in self.images
        ]
        tail = "isohybrid" if self.has_isohybrid else ""
        if self.has_gpt:
            tail += " +GPT" if tail else "GPT"
        return ", ".join(parts) + (f" | {tail}" if tail else "")


# --------------------------------------------------------------------------
# line parsers
# --------------------------------------------------------------------------

_RE_VOLID = re.compile(r"^Volume Id\s*:\s*(.+?)\s*$")
_RE_IMG = re.compile(
    r"^El Torito boot img\s*:\s+(\d+)\s+(\S+)\s+([yn])\s+(\S+)\s+\S+\s+\S+\s+(\d+)\s+\d+\s*$"
)
_RE_IMG_PATH = re.compile(r"^El Torito img path\s*:\s+(\d+)\s+(\S+)")
_RE_IMG_OPTS = re.compile(r"^El Torito img opts\s*:\s+(\d+)\s+(.+?)\s*$")
_RE_CAT_PATH = re.compile(r"^El Torito cat path\s*:\s+(\S+)")
_RE_SYSAREA_SUMMARY = re.compile(r"^System area summary:\s*(.+?)\s*$")
_RE_MBR_PART = re.compile(
    r"^MBR partition\s*:\s+(\d+)\s+(0x[0-9A-Fa-f]+)\s+(0x[0-9A-Fa-f]+)\s+(\d+)\s+(\d+)\s*$"
)


def parse_pvd(text: str) -> str:
    for line in text.splitlines():
        if m := _RE_VOLID.match(line):
            return m.group(1)
    return ""


def parse_el_torito(text: str) -> tuple[str | None, list[ElToritoImage]]:
    catalog: str | None = None
    images: list[ElToritoImage] = []

    for line in text.splitlines():
        if m := _RE_IMG.match(line):
            images.append(
                ElToritoImage(
                    index=int(m.group(1)),
                    platform=m.group(2),
                    bootable=m.group(3) == "y",
                    emulation=m.group(4),
                    load_size=int(m.group(5)),
                )
            )
        elif m := _RE_IMG_PATH.match(line):
            idx = int(m.group(1))
            for img in images:
                if img.index == idx:
                    img.path = m.group(2)
        elif m := _RE_IMG_OPTS.match(line):
            idx = int(m.group(1))
            opts = m.group(2)
            for img in images:
                if img.index == idx:
                    img.boot_info_table = "boot-info-table" in opts
                    img.isohybrid_suitable = "isohybrid-suitable" in opts
        elif m := _RE_CAT_PATH.match(line):
            catalog = m.group(1)

    return catalog, images


def parse_system_area(
    text: str,
) -> tuple[str, list[MbrPartition]]:
    summary = ""
    parts: list[MbrPartition] = []
    for line in text.splitlines():
        if m := _RE_SYSAREA_SUMMARY.match(line):
            summary = m.group(1)
        elif m := _RE_MBR_PART.match(line):
            parts.append(
                MbrPartition(
                    status=m.group(2),
                    part_type=m.group(3),
                    start=int(m.group(4)),
                    blocks=int(m.group(5)),
                )
            )
    return summary, parts


# --------------------------------------------------------------------------
# xorriso invocations
# --------------------------------------------------------------------------


def _indev_args(source: str, tool: str) -> list[str]:
    return [tool, "-indev", source]


def probe(source: str, tool_state: tools.ToolState | None = None) -> BootSpec:
    ts = tool_state or tools.locate()
    xorriso = ts.path("xorriso")

    if not os.path.isfile(source):
        raise ProbeError(f"ISO file not found: {source}")

    pvd = run_ok([*_indev_args(source, xorriso), "-pvd_info"])
    plain = run_ok(
        [
            *_indev_args(source, xorriso),
            "-report_el_torito",
            "plain",
            "-report_system_area",
            "plain",
        ]
    )
    # `-report_el_torito cmd` prints the combined boot reproduction command
    # list (el torito + system area); verified equal to the system_area one.
    cmd_out = run_ok([*_indev_args(source, xorriso), "-report_el_torito", "cmd"])

    catalog, images = parse_el_torito(plain)
    summary, parts = parse_system_area(plain)

    return BootSpec(
        source=source,
        iso_size=os.path.getsize(source),
        volume_id=parse_pvd(pvd),
        system_area_summary=summary,
        el_torito_catalog=catalog,
        images=images,
        mbr_partitions=parts,
        el_cmd_output=cmd_out,
        sys_cmd_output=cmd_out,
    )


# --------------------------------------------------------------------------
# file listing (in-ISO browse, no extraction)
# --------------------------------------------------------------------------

_RE_LSDL = re.compile(
    r"^([-dlbcpsw-][rwxstST-]{9})\s+\d+\s+\d+\s+\d+\s+(\d+)\s+\S+\s+\d+\s+\S+\s+(.*)$"
)


def _unquote(name: str) -> str:
    if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
        return name[1:-1]
    return name


def _parse_lsdl(line: str) -> IsoNode | None:
    m = _RE_LSDL.match(line)
    if not m:
        return None
    mode, size, rest = m.group(1), int(m.group(2)), m.group(3)
    p = _unquote(rest.strip())
    link = None
    if " -> " in p:
        p, link = p.split(" -> ", 1)
    is_dir = mode[0] == "d"
    is_link = mode[0] == "l"
    return IsoNode(
        path=p,
        name=os.path.basename(p) or p,
        mode=mode,
        is_dir=is_dir,
        is_link=is_link,
        size=size if not (is_dir or is_link) else 0,
    )


def list_dir(source: str, iso_dir: str, tool_state: tools.ToolState | None = None) -> list[IsoNode]:
    """List direct children of iso_dir inside source. iso_dir is an ISO path."""
    ts = tool_state or tools.locate()
    out = run_ok(
        [
            *_indev_args(source, ts.path("xorriso")),
            "-find",
            iso_dir,
            "-maxdepth",
            "1",
            "-exec",
            "lsdl",
        ]
    )
    nodes: list[IsoNode] = []
    for line in out.splitlines():
        node = _parse_lsdl(line)
        if node is None or node.path == iso_dir:
            continue
        nodes.append(node)
    return nodes