"""Unit tests for syso backend parsing & argv assembly (no subprocesses)."""

from __future__ import annotations

import os
import pathlib

import pytest

from syso.backend import rebuild as R
from syso.backend import tools as toolmod
from syso.backend.probe import (
    BootSpec,
    ElToritoImage,
    MbrPartition,
    parse_el_torito,
    parse_pvd,
    parse_system_area,
    list_dir,
    _parse_lsdl,
)
from syso import jobs

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
class FakeTools:
    def __init__(self, paths=None):
        self.tools = {
            "xorriso": "/usr/bin/xorriso",
            "osirrox": "/usr/bin/osirrox",
            "implantisomd5": "/usr/bin/implantisomd5",
            "checkisomd5": "/usr/bin/checkisomd5",
        }
        if paths:
            self.tools.update(paths)
        self.isohdpfx = "/usr/share/syslinux/isohdpfx.bin"

    def path(self, name):
        import syso.backend.tools as t

        p = self.tools.get(name, "")
        if not p:
            raise t.MissingToolError(name)
        return p


@pytest.fixture
def ts():
    return FakeTools()


# ---------------------------------------------------------------------------
def test_parse_pvd():
    assert parse_pvd(_read("pvd_info.txt")) == "TESTISO"


def test_parse_el_torito_hybrid():
    catalog, images = parse_el_torito(_read("el_sys_plain.txt"))
    assert catalog == "/isolinux/boot.cat"
    assert len(images) == 2
    b, e = images
    assert b.platform == "BIOS" and b.path == "/isolinux/isolinux.bin"
    assert b.boot_info_table is True
    assert b.load_size == 4
    assert e.platform == "UEFI" and e.path == "/boot/grub/efi.img"
    assert e.boot_info_table is False


def test_parse_system_area_hybrid():
    summary, parts = parse_system_area(_read("el_sys_plain.txt"))
    assert "isohybrid" in summary and "GPT" in summary
    assert len(parts) == 2
    assert parts[0].status == "0x80"
    assert parts[1].part_type == "0xef"


def test_bootspec_properties():
    spec = BootSpec(
        source="x.iso",
        iso_size=1,
        system_area_summary="MBR isohybrid cyl-align-on GPT",
        el_torito_catalog="/isolinux/boot.cat",
        images=[
            ElToritoImage(1, "BIOS", True, "none", 4, "/isolinux/isolinux.bin", True),
            ElToritoImage(2, "UEFI", True, "none", 576, "/boot/grub/efi.img", False),
        ],
    )
    assert spec.has_isohybrid and spec.has_gpt
    assert spec.bios_image == "/isolinux/isolinux.bin"
    assert spec.efi_image == "/boot/grub/efi.img"
    assert spec.boot_info_table is True
    assert "BIOS" in spec.summary and "isohybrid" in spec.summary


def test_parse_lsdl():
    node = _parse_lsdl(
        "drwxr-xr-x    1 1000     1000            0 Sep 14 23:41 '/preseed'"
    )
    assert node is not None and node.is_dir and node.path == "/preseed"
    node = _parse_lsdl(
        "-rw-r--r--    1 1000     1000       131072 Sep 14 23:41 '/initrd'"
    )
    assert node is not None and not node.is_dir and node.size == 131072


def test_list_dir_parses_top_level():
    # Use the captured lsdl text directly through the line parser.
    lines = _read("lsdl_top.txt").splitlines()
    nodes = [n for n in (_parse_lsdl(l) for l in lines) if n is not None]
    names = {n.name for n in nodes}
    assert "boot" in names and "initrd" in names and "preseed" in names


# ---------------------------------------------------------------------------
def test_plain_iso_has_no_boot():
    catalog, images = parse_el_torito(_read("plain_el_sys.txt"))
    assert catalog is None and images == []
    summary, _parts = parse_system_area(_read("plain_el_sys.txt"))
    assert not summary


def test_rebuild_argv_hybrid(ts, tmp_path):
    wd = tmp_path / "work"
    os.makedirs(wd / "isolinux")
    os.makedirs(wd / "boot" / "grub")
    (wd / "isolinux" / "isolinux.bin").write_bytes(b"x")
    (wd / "boot" / "grub" / "efi.img").write_bytes(b"x")
    spec = BootSpec(
        source="src.iso",
        iso_size=1,
        volume_id="SRCISO",
        system_area_summary="MBR isohybrid cyl-align-on GPT",
        el_torito_catalog="/isolinux/boot.cat",
        images=[
            ElToritoImage(1, "BIOS", True, "none", 4, "/isolinux/isolinux.bin", True),
            ElToritoImage(2, "UEFI", True, "none", 576, "/boot/grub/efi.img", False),
        ],
    )
    argv = R.rebuild_argv_xorriso(spec, str(wd), "/tmp/out.iso", tool_state=ts)
    joined = " ".join(argv)
    assert "-as" in argv and "mkisofs" in argv
    assert "-isohybrid-mbr" in joined and "-isohybrid-gpt-basdat" in joined
    assert "-b" in joined and "isolinux/isolinux.bin" in joined
    assert "-boot-info-table" in joined
    assert "-e" in joined and "boot/grub/efi.img" in joined
    assert argv[-1] == str(wd)


def test_rebuild_argv_bios_only(ts, tmp_path):
    wd = tmp_path / "work"
    os.makedirs(wd / "isolinux")
    (wd / "isolinux" / "isolinux.bin").write_bytes(b"x")
    spec = BootSpec(
        source="s.iso",
        iso_size=1,
        system_area_summary="",
        el_torito_catalog="/isolinux/boot.cat",
        images=[ElToritoImage(1, "BIOS", True, "none", 4, "/isolinux/isolinux.bin", False)],
    )
    argv = R.rebuild_argv_xorriso(spec, str(wd), "/tmp/out.iso", tool_state=ts)
    joined = " ".join(argv)
    assert "-b" in joined
    assert "-boot-info-table" not in joined
    assert "-eltorito-alt-boot" not in joined
    assert "-isohybrid-mbr" not in joined


def test_rebuild_argv_efi_only(ts, tmp_path):
    wd = tmp_path / "work"
    os.makedirs(wd / "boot" / "grub")
    (wd / "boot" / "grub" / "efi.img").write_bytes(b"x")
    spec = BootSpec(
        source="s.iso",
        iso_size=1,
        system_area_summary="GPT",
        el_torito_catalog=None,
        images=[ElToritoImage(1, "UEFI", True, "none", 576, "/boot/grub/efi.img", False)],
    )
    argv = R.rebuild_argv_xorriso(spec, str(wd), "/tmp/out.iso", tool_state=ts)
    assert "-eltorito-alt-boot" in argv and "-e" in argv
    assert "-b" not in argv and "-isohybrid-mbr" not in argv


def test_rebuild_argv_missing_boot_file_raises(ts, tmp_path):
    wd = tmp_path / "work"
    os.makedirs(wd)
    spec = BootSpec(
        source="s.iso",
        iso_size=1,
        system_area_summary="isohybrid",
        el_torito_catalog="/isolinux/boot.cat",
        images=[ElToritoImage(1, "BIOS", True, "none", 4, "/isolinux/isolinux.bin", False)],
    )
    with pytest.raises(R.RebuildError):
        R.rebuild_argv_xorriso(spec, str(wd), "/tmp/out.iso", tool_state=ts)


def test_sanitize_volid():
    assert R.sanitize_volid("My Label: 仮") == "My_Label___"
    assert R.sanitize_volid(None, "FALL") == "FALL"
    assert len(R.sanitize_volid("x" * 50)) <= 32


def test_pipeline_argv_steps(ts, tmp_path):
    wd = tmp_path / "work"
    os.makedirs(wd)
    spec = BootSpec(source="s.iso", iso_size=1)
    steps = R.build_pipeline_argv(spec, str(wd), "/tmp/out.iso", tool_state=ts)
    assert steps
    assert os.path.basename(steps[0][0]) == "xorriso"
    assert os.path.basename(steps[-1][0]) == "checkisomd5"


# ---------------------------------------------------------------------------
def test_job_percent():
    assert jobs.extract_percent("xorriso : UPDATE :  50% done") == 50.0
    assert jobs.extract_percent("some line 12.5% here") == 12.5
    assert jobs.extract_percent("no numbers") is None


def test_tool_locate_has_paths():
    state = toolmod.locate()
    assert state.path("xorriso")
    assert state.path("osirrox")


def test_lsdl_iso_node_binary_flag():
    node = _parse_lsdl("-rw-r--r--    1 1000     1000       131072 Sep 14 23:41 '/initrd'")
    assert node.is_binary