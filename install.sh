#!/usr/bin/env bash
# Installs driver files; configure-printer.sh creates a queue separately.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
STAGE= NO_DEPS=0 PREBUILT=0 SERVERBIN= DRIVER=python
usage() {
  cat <<'EOF'
Usage: sudo bash install.sh [--no-deps] [--prebuilt] [--serverbin PATH]
       bash install.sh --stage DIRECTORY [--no-deps] [--prebuilt]
  Default: compile for this Linux machine and install into CUPS 2.x.
  --stage: create portable Docker bind-mount files without changing CUPS.
  --prebuilt: use the included library for this Linux/glibc CPU architecture.
  --no-deps: skip apt; required dependencies must already be installed.
  --driver python|c: Python is the default; C consumes the same raster input.
  Queue creation, sharing, and test printing are separate explicit steps.
EOF
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --stage) STAGE=${2:?--stage requires a directory}; shift 2 ;;
    --serverbin) SERVERBIN=${2:?--serverbin requires a path}; shift 2 ;;
    --no-deps) NO_DEPS=1; shift ;;
    --prebuilt) PREBUILT=1; shift ;;
    --driver) DRIVER=${2:?--driver requires python or c}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ $DRIVER == python || $DRIVER == c ]] || die '--driver must be python or c.'
[[ $(uname -s) == Linux ]] || die 'This installer targets Linux with CUPS 2.x.'
[[ -n $STAGE || $EUID == 0 ]] || die 'Use sudo for a system installation.'
if ((PREBUILT)); then
  case $(uname -m) in
    armv7*|armv8l) PREBUILT_ARCH=linux-armv7-glibc ;;
    aarch64|arm64) PREBUILT_ARCH=linux-aarch64-glibc ;;
    x86_64|amd64) PREBUILT_ARCH=linux-x86_64-glibc ;;
    *) die 'No prebuilt library for this CPU; compile from source.' ;;
  esac
  getconf GNU_LIBC_VERSION >/dev/null 2>&1 || die '--prebuilt requires glibc; compile on other libc systems.'
fi
if ((!NO_DEPS)); then
  command -v apt-get >/dev/null || die 'Automatic dependencies support Debian/Ubuntu only; install dependencies manually and use --no-deps.'
  [[ $EUID == 0 ]] || die 'Dependency installation requires root; use sudo or --no-deps.'
  packages=(python3 python3-pil)
  ((PREBUILT)) || packages+=(gcc libc6-dev)
  [[ -n $STAGE ]] || packages+=(cups cups-client cups-filters ghostscript)
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}"
fi
command -v python3 >/dev/null || die 'python3 is missing.'
((PREBUILT)) || command -v "${CC:-cc}" >/dev/null || die 'C compiler missing; install gcc and libc6-dev.'
if [[ -z $STAGE ]]; then
  command -v lpadmin >/dev/null || die 'CUPS is missing; install cups and cups-client.'
  if command -v cups-config >/dev/null; then
    [[ $(cups-config --version) == 2.* ]] || die 'This PPD/filter driver requires CUPS 2.x.'
    SERVERBIN=${SERVERBIN:-$(cups-config --serverbin)}
  fi
  if [[ -z $SERVERBIN ]]; then
    SERVERBIN=/usr/lib/cups
    [[ ! -d /usr/libexec/cups/filter ]] || SERVERBIN=/usr/libexec/cups
    [[ ! -d /usr/lib64/cups/filter ]] || SERVERBIN=/usr/lib64/cups
  fi
fi
TEMP=$(mktemp -d)
trap 'rm -rf -- "$TEMP"' EXIT
if ((PREBUILT)); then
  cp -- "$ROOT/prebuilt/$PREBUILT_ARCH/libjbigwrap.so" "$TEMP/libjbigwrap.so"
else
  bash "$ROOT/build-native.sh" "$TEMP/libjbigwrap.so"
fi
# Validate the native ABI, encoding, frame lengths and filter invocation before installation.
python3 "$ROOT/tests/selftest.py" --library "$TEMP/libjbigwrap.so" --filter "$ROOT/rastertolkpl"
FILTER="$ROOT/rastertolkpl"
if [[ $DRIVER == c ]]; then
  if ((PREBUILT)); then
    [[ -f "$ROOT/prebuilt/$PREBUILT_ARCH/rastertolkpl-c" ]] || die 'No C binary for this architecture; omit --prebuilt to compile.'
    install -m 0755 "$ROOT/prebuilt/$PREBUILT_ARCH/rastertolkpl-c" "$TEMP/rastertolkpl-c"
  else
    bash "$ROOT/build-c.sh" "$TEMP/rastertolkpl-c"
  fi
  python3 "$ROOT/tests/compare_drivers.py" --native "$TEMP/rastertolkpl-c" \
    --library "$TEMP/libjbigwrap.so" --report "$TEMP/c-parity.json"
  FILTER="$TEMP/rastertolkpl-c"
fi
if command -v cupstestppd >/dev/null; then
  # Pre-install: the referenced filter is not installed yet. The smoke test
  # repeats the full check after copying it to the real filter directory.
  cupstestppd -I filters -q "$ROOT/ppd/Lenovo-LJ2268.ppd"
fi
if [[ -n $STAGE ]]; then
  mkdir -p -- "$STAGE/ppd" "$STAGE/usb"
  install -m 0755 "$FILTER" "$STAGE/rastertolkpl"
  install -m 0644 "$TEMP/libjbigwrap.so" "$STAGE/libjbigwrap.so"
  install -m 0644 "$ROOT/ppd/Lenovo-LJ2268.ppd" "$STAGE/ppd/Lenovo-LJ2268.ppd"
  install -m 0644 "$ROOT/usb/lenovo-lj2268-unidir" "$STAGE/usb/lenovo-lj2268-unidir"
  printf '%s driver staged at %s. Rebuild it when changing CPU architecture or libc.\n' "$DRIVER" "$STAGE"
else
  BACKUP=$(mktemp -d /var/tmp/lj2268-driver-backup.XXXXXX)
  targets=("$SERVERBIN/filter/rastertolkpl" /usr/local/lib/libjbigwrap.so \
    /usr/share/ppd/lenovo/Lenovo-LJ2268.ppd /usr/share/cups/model/Lenovo-LJ2268.ppd /usr/share/cups/usb/lenovo-lj2268-unidir)
  for target in "${targets[@]}"; do
    if [[ -e $target ]]; then
      mkdir -p -- "$BACKUP$(dirname -- "$target")"
      cp -a -- "$target" "$BACKUP$target"
    fi
  done
  install -d "$SERVERBIN/filter" /usr/local/lib /usr/share/ppd/lenovo /usr/share/cups/model /usr/share/cups/usb
  install -o root -g root -m 0755 "$FILTER" "$SERVERBIN/filter/rastertolkpl"
  install -o root -g root -m 0644 "$TEMP/libjbigwrap.so" /usr/local/lib/libjbigwrap.so
  install -o root -g root -m 0644 "$ROOT/ppd/Lenovo-LJ2268.ppd" /usr/share/ppd/lenovo/Lenovo-LJ2268.ppd
  install -o root -g root -m 0644 "$ROOT/ppd/Lenovo-LJ2268.ppd" /usr/share/cups/model/Lenovo-LJ2268.ppd
  install -o root -g root -m 0644 "$ROOT/usb/lenovo-lj2268-unidir" /usr/share/cups/usb/lenovo-lj2268-unidir
  printf '%s driver installed. Previous files: %s\nNext: sudo bash configure-printer.sh\n' "$DRIVER" "$BACKUP"
fi
