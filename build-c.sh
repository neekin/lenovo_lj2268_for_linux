#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
OUT=${1:-"$ROOT/build/rastertolkpl-c"}
python3 "$ROOT/tools/generate_c_tables.py" --check
mkdir -p -- "$(dirname -- "$OUT")"
TEMP=$(mktemp -d)
trap 'rm -rf -- "$TEMP"' EXIT
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror -I"$ROOT/source/jbigkit" \
  -c "$ROOT/source/rastertolkpl.c" -o "$TEMP/driver.o"
"${CC:-cc}" -O2 -I"$ROOT/source/jbigkit" -c "$ROOT/source/jbigkit/jbig.c" -o "$TEMP/jbig.o"
"${CC:-cc}" -O2 -I"$ROOT/source/jbigkit" -c "$ROOT/source/jbigkit/jbig_ar.c" -o "$TEMP/jbig_ar.o"
"${CC:-cc}" "$TEMP/driver.o" "$TEMP/jbig.o" "$TEMP/jbig_ar.o" -o "$OUT"
printf 'Built C raster filter %s for %s\n' "$OUT" "$(uname -m)"
