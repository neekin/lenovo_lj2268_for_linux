#!/usr/bin/env bash
# Package the already-built native C filter; never builds for another CPU here.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
BINARY=${1:-"$ROOT/build/rastertolkpl-c"}
OUTPUT=${2:-"$ROOT/build/packages"}
[[ -x $BINARY ]] || { echo 'Build the C driver first: bash build-c.sh' >&2; exit 1; }
ARCH=$(dpkg --print-architecture)
case "$ARCH" in armhf|arm64|amd64) ;; *) echo "Unsupported package architecture: $ARCH" >&2; exit 1 ;; esac
VERSION=$(cat "$ROOT/VERSION")
TEMP=$(mktemp -d)
trap 'rm -rf -- "$TEMP"' EXIT
mkdir -p "$TEMP/DEBIAN" "$TEMP/usr/lib/cups/filter" "$TEMP/usr/share/ppd/lenovo" \
  "$TEMP/usr/share/cups/usb" "$TEMP/usr/share/doc/lenovo-lj2268" "$OUTPUT"
install -m 0755 "$BINARY" "$TEMP/usr/lib/cups/filter/rastertolkpl"
install -m 0644 "$ROOT/ppd/Lenovo-LJ2268.ppd" "$TEMP/usr/share/ppd/lenovo/Lenovo-LJ2268.ppd"
install -m 0644 "$ROOT/usb/lenovo-lj2268-unidir" "$TEMP/usr/share/cups/usb/lenovo-lj2268-unidir"
install -m 0644 "$ROOT/source/jbigkit/COPYING" "$TEMP/usr/share/doc/lenovo-lj2268/COPYING.JBIG-KIT"
install -m 0644 "$ROOT/LICENSE" "$TEMP/usr/share/doc/lenovo-lj2268/LICENSE.project"
install -m 0644 "$ROOT/THIRD_PARTY.md" "$TEMP/usr/share/doc/lenovo-lj2268/copyright"
# Include corresponding source in the package as well as in Git/ZIP releases.
tar -czf "$TEMP/usr/share/doc/lenovo-lj2268/source.tar.gz" -C "$ROOT" \
  source rastertolkpl build-c.sh tools/generate_c_tables.py LICENSE THIRD_PARTY.md
MIN_GLIBC=$(python3 - "$BINARY" <<'PY'
from pathlib import Path
import re, sys
versions = {x.decode() for x in re.findall(rb'GLIBC_(\d+\.\d+(?:\.\d+)?)', Path(sys.argv[1]).read_bytes())}
assert versions, 'Cannot determine required glibc version'
print(max(versions, key=lambda x: tuple(map(int, x.split('.')))))
PY
)
cat > "$TEMP/DEBIAN/control" <<EOF
Package: lenovo-lj2268
Version: $VERSION
Architecture: $ARCH
Maintainer: neekin <neekin@users.noreply.github.com>
Section: text
Priority: optional
Depends: libc6 (>= $MIN_GLIBC), cups (>= 2.2), cups (<< 3.0), cups-filters
Homepage: https://github.com/neekin/lenovo_lj2268_for_linux
Description: Lenovo LJ2268 CUPS native C raster driver
 Includes a compiled LHPL filter, PPD, USB quirk and corresponding sources.
 Add the USB printer in the CUPS web interface after installation.
EOF
dpkg-deb --root-owner-group --build "$TEMP" "$OUTPUT/lenovo-lj2268_${VERSION}_${ARCH}.deb"
