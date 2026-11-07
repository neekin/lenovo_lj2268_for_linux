#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
OUT=${1:-"$ROOT/build/libjbigwrap.so"}
mkdir -p -- "$(dirname -- "$OUT")"
"${CC:-cc}" -O2 -fPIC -shared -I"$ROOT/source/jbigkit" \
  "$ROOT/source/lhpl_jbig_wrap.c" "$ROOT/source/jbigkit/jbig.c" \
  "$ROOT/source/jbigkit/jbig_ar.c" -o "$OUT"
printf 'Built %s for %s\n' "$OUT" "$(uname -m)"
