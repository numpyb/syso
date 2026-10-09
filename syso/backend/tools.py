"""Locate the external tools syso wraps, and their supporting files."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


ISOHDPFX_CANDIDATES = (
    "/usr/share/syslinux/isohdpfx.bin",
    "/usr/lib/ISOLINUX/isohdpfx.bin",
    "/usr/lib/syslinux/mbr/isohdpfx.bin",
)

REQUIRED = ("xorriso", "osirrox")

_TOOL_BINARIES = {
    "xorriso": ("xorriso",),
    "osirrox": ("osirrox",),
    "isohybrid": ("isohybrid",),
    "genisoimage": ("genisoimage", "mkisofs"),
    "implantisomd5": ("implantisomd5",),
    "checkisomd5": ("checkisomd5",),
    "lsblk": ("lsblk",),
    "dd": ("dd",),
}


class MissingToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolState:
    tools: dict[str, str]
    isohdpfx: str | None

    def path(self, name: str) -> str:
        p = self.tools.get(name, "")
        if not p:
            raise MissingToolError(f"tool not available: {name}")
        return p

    @property
    def missing(self) -> list[str]:
        return [name for name, path in self.tools.items() if not path]

    @property
    def fatal_missing(self) -> list[str]:
        return [n for n in REQUIRED if not self.tools.get(n)]


def locate() -> ToolState:
    tools: dict[str, str] = {}
    for name, candidates in _TOOL_BINARIES.items():
        for cand in candidates:
            found = shutil.which(cand)
            if found:
                tools[name] = found
                break
        else:
            tools[name] = ""
    mbr = next((p for p in ISOHDPFX_CANDIDATES if os.path.isfile(p)), None)
    return ToolState(tools=tools, isohdpfx=mbr)