#!/usr/bin/env bash
# CI only: convert a sample PDF offline, then create a non-printing test queue.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$ROOT/build"
cupstestppd -q "$ROOT/ppd/Lenovo-LJ2268.ppd"
cupsfilter -p "$ROOT/ppd/Lenovo-LJ2268.ppd" -i application/pdf \
  -m application/vnd.cups-raster "$ROOT/tests/fixtures/hello.pdf" \
  > "$ROOT/build/cups-smoke.raster" 2> "$ROOT/build/cups-raster.log"
"${LHPL_SMOKE_FILTER:-$ROOT/rastertolkpl}" 1 ci 'CUPS PDF conversion' 1 '' \
  "$ROOT/build/cups-smoke.raster" > "$ROOT/build/cups-smoke.prn"
python3 - "$ROOT/build/cups-smoke.prn" <<'PY'
from pathlib import Path
import struct, sys
data = Path(sys.argv[1]).read_bytes()
sp = data.index(b'\x1bLH@sp')
length = struct.unpack_from('<I', data, sp + 6 + 0x0e)[0]
assert length > 20
assert data[sp + 64 + length:sp + 64 + length + 6] == b'\x1bLH@ep'
assert data.endswith(b'@PJL EOJ\r\n')
print('CUPS PDF -> raster -> LHPL: passed (no print job submitted)')
PY
if [[ ${CI:-} == true ]]; then
  sudo systemctl start cups
  sudo bash "$ROOT/configure-printer.sh" --queue LJ2268_CI --uri socket://127.0.0.1:9
  # Verify the real queue uses this driver, but never submit a job to it.
  lpstat -v LJ2268_CI
  grep -q 'rastertolkpl' /etc/cups/ppd/LJ2268_CI.ppd || sudo grep -q 'rastertolkpl' /etc/cups/ppd/LJ2268_CI.ppd
  if sudo bash "$ROOT/configure-printer.sh" --queue LJ2268_CI --uri socket://127.0.0.1:9; then
    echo 'Existing-queue protection failed' >&2
    exit 1
  fi
  sudo bash "$ROOT/configure-printer.sh" --update --queue LJ2268_CI --uri socket://127.0.0.1:9
  sudo lpadmin -x LJ2268_CI
fi
