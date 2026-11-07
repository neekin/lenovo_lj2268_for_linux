#!/usr/bin/env bash
set -euo pipefail
CONTAINER= QUEUE=Lenovo_LJ2268 URI= SHARE=0 DEFAULT=0 UPDATE=0
PPD=/usr/share/ppd/lenovo/Lenovo-LJ2268.ppd
usage() {
  cat <<'EOF'
Usage: sudo bash configure-printer.sh [options]
       bash configure-printer.sh --container cups [options]
  --uri URI         Explicit usb://... or socket://... device address
  --queue NAME      Default: Lenovo_LJ2268
  --share           Share this queue and enable local-network CUPS sharing
  --set-default     Set this queue as the server's default
  --update          Update an existing queue (without deleting it)
  --container NAME  Execute CUPS commands inside an existing container
No page is printed by this script. With no URI, exactly one LJ2268 USB is required.
EOF
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --container) CONTAINER=${2:?Missing container}; shift 2 ;;
    --queue) QUEUE=${2:?Missing queue}; shift 2 ;;
    --uri) URI=${2:?Missing URI}; shift 2 ;;
    --share) SHARE=1; shift ;;
    --set-default) DEFAULT=1; shift ;;
    --update) UPDATE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ $QUEUE =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]] || die 'Invalid queue name.'
if [[ -n $CONTAINER ]]; then
  command -v docker >/dev/null || die 'Docker is missing.'
  RUN=(docker exec --user 0 "$CONTAINER")
else
  [[ $EUID == 0 ]] || die 'Use sudo, or --container cups.'
  RUN=()
fi
"${RUN[@]}" test -f "$PPD" || die 'Install the driver in the CUPS environment first.'
"${RUN[@]}" lpstat -r
if "${RUN[@]}" lpstat -p "$QUEUE" >/dev/null 2>&1 && ((!UPDATE)); then
  die "Queue $QUEUE exists; use --update or choose another --queue."
fi
if [[ -z $URI ]]; then
  DEVICES=$("${RUN[@]}" lpinfo -v)
  MATCHES=()
  while IFS= read -r line; do
    if [[ $line =~ ^direct[[:space:]]+(usb://[^[:space:]]+) ]]; then
      candidate=${BASH_REMATCH[1]}
      if [[ ${candidate,,} == usb://lenovo/lj2268\?* || ${candidate,,} == usb://lenovo/lj2268 ]]; then
        MATCHES+=("$candidate")
      fi
    fi
  done <<< "$DEVICES"
  ((${#MATCHES[@]} == 1)) || die 'No unique LJ2268 USB found. Run lpinfo -v (inside CUPS container if used) and specify --uri.'
  URI=${MATCHES[0]}
fi
case "$URI" in usb://*|socket://*|ipp://*|ipps://*|lpd://*) ;; *) die 'Unsupported device URI.' ;; esac
"${RUN[@]}" lpadmin -p "$QUEUE" -E -v "$URI" -P "$PPD" \
  -D 'Lenovo LJ2268' -o PageSize=A4 -o ColorModel=Gray \
  -o printer-error-policy=retry-job -o cupsSNMPSupplies=false
if ((SHARE)); then
  "${RUN[@]}" lpadmin -p "$QUEUE" -o printer-is-shared=true
  "${RUN[@]}" cupsctl --share-printers
fi
if ((DEFAULT)); then "${RUN[@]}" lpadmin -d "$QUEUE"; fi
"${RUN[@]}" lpstat -v "$QUEUE"
printf 'Queue configured. No print job submitted. See docs/CUPS.md and docs/AIRPRINT.md.\n'
