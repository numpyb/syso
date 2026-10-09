# syso — bootable ISO workbench

A light GTK4 desktop app to **probe · extract · edit · repack** bootable ISOs:
browse inside a disc without extracting it, explode it to a working directory,
edit preseed / kickstart / grub / syslinux configs in a built-in editor, then
rebuild a boots-hybrid ISO (BIOS **and** UEFI) that keeps its bootability.

Everything is driven by the battle-tested **xorriso** engine (with
`implantisomd5` / `checkisomd5` for integrity), so the app stays small and the
underlying tools stay the source of truth.

## Requirements

- Python ≥ 3.10 with **PyGObject + GTK4** (`gi.require_version("Gtk", "4.0")`)
- CLI tools: `xorriso`, `osirrox` (package: `libisoburn`/`xorriso`)
- Optional: `implantisomd5`, `checkisomd5` (MD5 embed/verify)
- Hybrid-MBR blob `/usr/share/syslinux/isohdpfx.bin` (Fedora/Debian ship it)

## Run

```sh
# if PyGObject is system-wide, run straight from source
python3 -m syso            # (from the project root)

# or install into a venv
python3 -m venv --system-site-packages .venv
.venv/bin/pip install .
.venv/bin/syso
```

## Workflow

1. **Inspector** — `Open ISO`, read volume id / boot images / system area, and
   browse the ISO file tree without touching the image (lazy, via xorriso).
2. **Workbench** — pick a working directory, `Extract ISO →`, then open/edit
   files (built-in editor for text configs, external app otherwise), add or
   delete files.
3. **Rebuild** — set the destination, volume label, checksum options; the
   command preview shows exactly what will run; `Build ISO`.

The rebuild only emits the boot options the source actually had, so BIOS-only,
UEFI-only, hybrid (isohybrid + GPT) and plain-data ISOs all come out right.

## Verify

```sh
xorriso -indev edited.iso -boot_image any show_status   # boot record preserved?
checkisomd5 edited.iso                                  # md5 ok?
mount -o loop,ro edited.iso /mnt && ls /mnt && umount /mnt
```

## Dev

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
./scripts/make_test_iso.sh build/test.iso     # build fixture hybrid ISO
timeout 40 .venv/bin/python scripts/smoke_gui.py   # full UI flow e2e
```

## Architecture

```
syso/backend      pure-stdlib wrappers: probe (BootSpec), extract, rebuild(argv), tools, runner
syso/jobs.py      streaming, cancellable subprocess jobs (GLib-safe)
syso/ui           GTK4 panes: inspector, workbench(+editor), rebuildform, log panel
syso/window.py    state + navigation; header theme = follow-system/light/dark
```

Adding a feature is a sibling module + one stack registration — no plugin
framework on purpose (see PLAYBOOK.md).

## Roadmap (pluggable seams left open)

- **M5** create-from-directory (`backend/create.py` + tab)
- **M6** write-to-USB (`backend/usbwrite.py`: lsblk list → confirm → dd → verify)
- Replay-based "preserve custom boot setups" rebuild (xorriso `-boot_image replay`,
  verified for in-place edits; full-tree replace is follow-up)

## Out of scope (v1)

Nested-content flattening (unsquashfs inside installers); Windows/macOS ISOs.