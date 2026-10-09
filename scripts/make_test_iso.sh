#!/usr/bin/env bash
set -euo pipefail

# Build a small hybrid (BIOS+UEFI) bootable fixture ISO used for development
# and end-to-end tests of syso. Not a real distro installer: isolinux.bin is
# real, everything else is placeholder content, but the El Torito and
# isohybrid system area metadata is genuine and gradable by xorriso.

OUT="${1:-build/test.iso}"
SRC=$(mktemp -d)
trap 'rm -rf "$SRC"' EXIT

ISOLINUX_BIN="${SYSO_ISOLINUX_BIN:-/usr/share/syslinux/isolinux.bin}"
ISOHDPFX_BIN="${SYSO_ISOHDPFX_BIN:-/usr/share/syslinux/isohdpfx.bin}"

mkdir -p "$SRC/isolinux" "$SRC/boot/grub" "$SRC/preseed"

cp "$ISOLINUX_BIN" "$SRC/isolinux/isolinux.bin"
[ -f "$ISOLINUX_BIN" ] || { echo "missing isolinux.bin" >&2; exit 1; }

# Real FAT filesystem as the EFI boot image.
EFI="$SRC/boot/grub/efi.img"
dd if=/dev/zero of="$EFI" bs=1k count=288 2>/dev/null
mkfs.vfat -n SYSOEFI "$EFI" >/dev/null
mmd -i "$EFI" ::/EFI ::/EFI/BOOT 2>/dev/null || true

cat > "$SRC/isolinux/isolinux.cfg" <<'EOF'
DEFAULT linux
LABEL linux
    KERNEL /vmlinuz
    APPEND initrd=/initrd quiet
EOF

dd if=/dev/zero of="$SRC/vmlinuz" bs=1k count=64 2>/dev/null
dd if=/dev/zero of="$SRC/initrd" bs=1k count=128 2>/dev/null

cat > "$SRC/boot/grub/grub.cfg" <<'EOF'
set timeout=5
menuentry "syso test" { linux /vmlinuz; initrd /initrd; }
EOF

cat > "$SRC/preseed/seed.cfg" <<'EOF'
d-i debian-installer/locale string en_US
d-i netcfg/get_hostname string syso-test
EOF

mkdir -p "$(dirname "$OUT")"
xorriso -as mkisofs \
  -o "$OUT" \
  -V TESTISO \
  -J -joliet-long -R \
  -f -no-pad \
  -isohybrid-mbr "$ISOHDPFX_BIN" \
  -b isolinux/isolinux.bin -c isolinux/boot.cat \
  -no-emul-boot -boot-load-size 4 -boot-info-table \
  -eltorito-alt-boot -e boot/grub/efi.img -no-emul-boot \
  -isohybrid-gpt-basdat \
  "$SRC"

echo "wrote $OUT"