"""Extraction of ISO contents to a working directory.

Functions here return argv lists; run them with syso.jobs (UI) for streaming
and cancellation, or syso.backend.runner (tests/scripts) for blocking runs.
"""

from __future__ import annotations

import os

from . import tools
from .runner import run_ok


def extract_full_argv(source: str, dest_dir: str, tool_state: tools.ToolState | None = None) -> list[str]:
    """Explode the whole ISO into dest_dir."""
    ts = tool_state or tools.locate()
    return [ts.path("osirrox"), "-indev", source, "-extract", "/", dest_dir]


def extract_node_argv(
    source: str,
    iso_path: str,
    dest_dir: str,
    tool_state: tools.ToolState | None = None,
) -> list[str]:
    """Extract a single file or directory tree from the ISO to dest_dir."""
    ts = tool_state or tools.locate()
    return [ts.path("osirrox"), "-indev", source, "-extract", iso_path, dest_dir]


def extract_single_file_argv(
    source: str,
    iso_path: str,
    dest_file: str,
    tool_state: tools.ToolState | None = None,
) -> list[str]:
    """Extract a single regular file to the absolute path dest_file."""
    ts = tool_state or tools.locate()
    return [
        ts.path("xorriso"),
        "-osirrox",
        "on",
        "-indev",
        source,
        "-extract_single",
        iso_path,
        dest_file,
    ]


def extract_boot_images_argv(
    source: str,
    dest_dir: str,
    tool_state: tools.ToolState | None = None,
) -> list[str]:
    """Copy the El Torito boot images into dest_dir with role-named files."""
    ts = tool_state or tools.locate()
    return [
        ts.path("osirrox"),
        "-indev",
        source,
        "-extract_boot_images",
        dest_dir,
    ]


def file_in_workdir(workdir: str, iso_path: str) -> str:
    """Map an absolute ISO path (e.g. /preseed/seed.cfg) into workdir."""
    rel = iso_path.lstrip("/")
    return os.path.join(workdir, rel)


def create_workdir(workdir: str) -> None:
    os.makedirs(workdir, exist_ok=True)