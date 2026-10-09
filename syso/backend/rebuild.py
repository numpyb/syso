"""Rebuild bootable ISOs from a working directory.

Only the parts that exist in the probed source are emitted, so BIOS-only,
EFI-only, hybrid, and plain-data ISOs all rebuild correctly. See PLAYBOOK.md
for the verified command shape.
"""

from __future__ import annotations

import os
import re

from . import tools
from .probe import BootSpec


class RebuildError(RuntimeError):
    pass


_VOLID_BAD = re.compile(r"[^A-Za-z0-9_\-.]")


def sanitize_volid(label: str | None, fallback: str = "SYSO") -> str:
    label = (label or "").strip() or fallback
    label = _VOLID_BAD.sub("_", label)
    label = label[:32] or "SYSO"
    return label


def _require_in_workdir(workdir: str, iso_path: str | None) -> str | None:
    if not iso_path:
        return None
    rel = iso_path.lstrip("/")
    base = os.path.abspath(workdir)
    candidate = os.path.normpath(os.path.join(base, rel))
    if os.path.commonpath([base, candidate]) != base:
        raise RebuildError(f"boot path escapes working dir: {iso_path}")
    if not os.path.exists(candidate):
        raise RebuildError(
            f"boot file missing in working dir; re-extract the ISO first:\n  {candidate}"
        )
    return rel


def rebuild_argv_xorriso(
    spec: BootSpec,
    workdir: str,
    out_iso: str,
    *,
    label: str | None = None,
    hybrid: bool | None = None,
    tool_state: tools.ToolState | None = None,
) -> list[str]:
    """argv for `xorriso -as mkisofs` structured rebuild (BIOS/EFI/hybrid/plain)."""
    ts = tool_state or tools.locate()
    wdir = os.path.abspath(workdir)
    if not os.path.isdir(wdir):
        raise RebuildError(f"working directory does not exist: {wdir}")
    if os.path.abspath(out_iso) == wdir:
        raise RebuildError("output ISO must not point at the working directory")

    label = sanitize_volid(label, spec.volume_id or "SYSO")

    bios = _require_in_workdir(wdir, spec.bios_image)
    efi = _require_in_workdir(wdir, spec.efi_image)
    catalog = spec.el_torito_catalog.lstrip("/") if spec.el_torito_catalog else None

    if bios and not catalog:
        raise RebuildError("EI Torito BIOS image present but no boot catalog path was probed")

    want_hybrid = spec.has_isohybrid if hybrid is None else hybrid and spec.has_isohybrid

    args = [
        ts.path("xorriso"),
        "-as",
        "mkisofs",
        "-o",
        out_iso,
        "-V",
        label,
        "-J",
        "-joliet-long",
        "-R",
        "-f",
        "-no-pad",
    ]

    if want_hybrid and ts.isohdpfx:
        args += ["-isohybrid-mbr", ts.isohdpfx]

    if bios:
        args += ["-b", bios, "-c", catalog, "-no-emul-boot", "-boot-load-size", "4"]
        if spec.boot_info_table:
            args += ["-boot-info-table"]

    if efi:
        args += ["-eltorito-alt-boot", "-e", efi, "-no-emul-boot"]
        if want_hybrid and spec.has_gpt:
            args += ["-isohybrid-gpt-basdat"]

    args.append(wdir)
    return args


def implant_argv(out_iso: str, tool_state: tools.ToolState | None = None) -> list[str]:
    ts = tool_state or tools.locate()
    return [ts.path("implantisomd5"), out_iso]


def verify_argv(out_iso: str, tool_state: tools.ToolState | None = None) -> list[str]:
    ts = tool_state or tools.locate()
    return [ts.path("checkisomd5"), out_iso]


def build_pipeline_argv(
    spec: BootSpec,
    workdir: str,
    out_iso: str,
    *,
    label: str | None = None,
    checksum: bool = True,
    verify: bool = True,
    tool_state: tools.ToolState | None = None,
) -> list[list[str]]:
    """The ordered list of subprocess avgs for a full rebuild job."""
    steps: list[list[str]] = [
        rebuild_argv_xorriso(spec, workdir, out_iso, label=label, tool_state=tool_state)
    ]
    ts = tool_state or tools.locate()
    if checksum and ts.tools.get("implantisomd5"):
        steps.append(implant_argv(out_iso, ts))
    if verify and ts.tools.get("checkisomd5"):
        steps.append(verify_argv(out_iso, ts))
    return steps