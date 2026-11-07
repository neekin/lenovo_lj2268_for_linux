#!/usr/bin/env bash
# Install the matching compiled C driver; no C compiler is required.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec bash "$ROOT/install.sh" --driver c --prebuilt "$@"
