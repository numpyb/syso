# PLAYBOOK — syso: Bootable ISO workbench (v1)

**Goal:** A light GTK4/Python desktop app to probe, explode, edit, and repack
bootable ISOs — insert/modify preseed/kickstart/grub configs, extract to a
working directory, and rebuild bootable hybrid ISOs. v1 = **open · extract ·
edit · repack**. Generate the *create-from-directory* (M5) and *USB writer*
(M6) as pluggable additions later.

**Project root:** this directory (`syso`)

## Decisions
- **Stack:** Python 3.14 + PyGObject GTK4; shells out to `xorriso` (primary).
- **Modular package, not a plugin system.** Sibling modules with clean seams
  are enough for M5/M6; a runtime plugin framework would only add cost.
- **Pipeline:** `probe → extract → edit (workdir) → rebuild → verify`.

## Required tools (preflight checks at startup)
- `xorriso`, `osirrox` (probing, extraction, rebuild — `xorriso -as mkisofs`)
- `/usr/share/syslinux/isohdpfx.bin` (hybrid MBR, source dependent)
- `implantisomd5`, `checkisomd5` (optional MD5 embed/verify)
- `genisoimage`/`mkisofs` (future alternate backend), `isohybrid`

## Core flows (validated empirically on this machine)
### Probe (read-only)
- `xorriso -indev X -pvd_info` → volume id
- `xorriso -indev X -report_el_torito plain -report_system_area plain` →
  `BootSpec` (BIOS/EFI image paths, boot catalog, boot-info-table, isohybrid MBR/GPT)
- `xorriso -indev X -report_el_torito cmd` → xorriso's own "reproduce boot
  equipment" commands (shown in inspector + replay)
- Browse without extracting: `xorriso -indev X -find /dir -maxdepth 1 -exec lsdl`

### Extract
- Full: `osirrox -indev X -extract / WORKDIR`
- Single: `xorriso -osirrox on -indev X -extract_single /path DEST`
- `-extract_boot_images` for boot blobs only

### Edit
- Working-directory file tree; built-in text editor for preseed/ks/grub.cfg/
  isolinux.cfg; external editor via `xdg-open`; add/import/delete files.

### Rebuild (structured, primary)
```
xorriso -as mkisofs -o OUT.iso -V LABEL -J -joliet-long -R -f -no-pad
  -isohybrid-mbr /usr/share/syslinux/isohdpfx.bin      # iff source isohybrid
  -b isolinux/isolinux.bin -c isolinux/boot.cat        # iff BIOS image probed
  -no-emul-boot -boot-load-size 4 -boot-info-table     # -boot-info-table iff probed
  -eltorito-alt-boot -e boot/grub/efi.img -no-emul-boot  # iff EFI image probed
  -isohybrid-gpt-basdat                                  # iff GPT + EFI
  WORKDIR/
```
Only emits options for parts that exist ⇒ BIOS-only / EFI-only / hybrid /
plain-data all handled. Post: `implantisomd5 OUT.iso`, verify `checkisomd5`.

### Rebuild (replay, advanced/experimental)
`xorriso -indev SRC -outdev OUT -boot_image any replay [tree ops]` preserves
arbitrary/custom boot equipment by replaying the commands xorriso itself
proposes. Validated for in-place file mapping. Full-tree replace (delete+map)
is follow-up work.

## Verified on this machine
- Fixture build: `scripts/make_test_iso.sh` (real isolinux.bin, FAT efi.img,
  `-isohybrid-gpt-basdat`).
- extract → edit → structured rebuild → `-boot_image any show_status` retains
  `El Torito , MBR isohybrid cyl-align-on GPT` with both images.

## v1 milestones
- M0 scaffold / playbook / pyproject          ✅
- M1 probe + inspector + in-ISO browse        ✅
- M2 workbench: extract, tree, editor, add/remove ✅
- M3 rebuild: structured argv, checksum, e2e verify (scripts/smoke_gui.py) ✅
- M4 polish: tests (16), theme, README, .desktop launcher ✅

## Small extras shipped
- Header-bar theme menu: Follow system / Light / Dark (`gtk-color-scheme`).
- Recent ISOs menu (`~/.config/syso/recent.txt`).
- Unit tests in tests/ (parsers vs captured xorriso fixtures; argv assembly).

## Out of scope v1 (pluggable seams left)
- M5 create-from-directory → add `backend/create.py` + a tab registration.
- M6 USB writer → add `backend/usbwrite.py` (lsblk list + confirm + dd + verify).
- Nested flattening (unsquashfs inside installers), Windows/macOS ISOs.

## Layout
```
syso/
  app.py  backend/{tools,runner,probe,extract,rebuild}.py  ui/{inspector,workbench,editor,rebuildform,panel}.py
tests/  scripts/make_test_iso.sh  data/syso.desktop  README.md
```