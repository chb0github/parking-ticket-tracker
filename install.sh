#!/usr/bin/env bash
# Portable installer for parking-ticket-tracker: sets up the venv and installs
# the cron job. Nothing is hardcoded — all paths derive from this script's
# location, and plates/recipients/schedule are arguments.
#
# Usage:
#   ./install.sh --plate PLATE [PLATE ...] --email-to ADDR [ADDR ...] \
#                [--schedule "M H DoM Mon DoW"] [--state-dir DIR] [--no-cron]
#
# Examples:
#   ./install.sh --plate BYP5855 --email-to me@example.com
#   ./install.sh --plate BYP5855 ABC1234 --email-to me@x.com you@y.com \
#                --schedule "7 8 * * 1"
#
# Defaults: weekly Mondays at 08:07 local; state dir $HOME/.local/state/parking-tickets.
set -euo pipefail

# --- resolve paths from this script's own location (portable) --------------
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
REPO_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
PY="$REPO_DIR/.venv/bin/python3"
TRACK="$REPO_DIR/track.py"
GIT="$(command -v git || echo /usr/bin/git)"       # absolute path (cron's PATH is minimal)

# --- defaults --------------------------------------------------------------
PLATES=()
EMAILS=()
SCHEDULE="7 8 * * 1"                                   # Mondays 08:07 local
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/parking-tickets"
INSTALL_CRON=1
MARKER="# parking-ticket-tracker (managed by install.sh)"

# --- parse args ------------------------------------------------------------
mode=""
while [ $# -gt 0 ]; do
  case "$1" in
    --plate)     mode="plate"; shift ;;
    --email-to)  mode="email"; shift ;;
    --schedule)  SCHEDULE="$2"; mode=""; shift 2 ;;
    --state-dir) STATE_DIR="$2"; mode=""; shift 2 ;;
    --no-cron)   INSTALL_CRON=0; mode=""; shift ;;
    -h|--help)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --*)         echo "unknown option: $1" >&2; exit 2 ;;
    *)
      case "$mode" in
        plate) PLATES+=("$1") ;;
        email) EMAILS+=("$1") ;;
        *) echo "unexpected argument: $1" >&2; exit 2 ;;
      esac
      shift ;;
  esac
done

if [ "${#PLATES[@]}" -eq 0 ]; then
  echo "error: at least one --plate is required" >&2
  exit 2
fi

echo "[install] repo:      $REPO_DIR"
echo "[install] plates:    ${PLATES[*]}"
echo "[install] email-to:  ${EMAILS[*]:-<track.py default>}"
echo "[install] state-dir: $STATE_DIR"

# --- 1. venv + python deps -------------------------------------------------
echo "[install] setting up venv ..."
bash "$REPO_DIR/setup.sh"

# --- 2. tesseract check (needed for OCR of fine/location) ------------------
if ! "$PY" -c "import pytesseract; pytesseract.get_tesseract_version()" >/dev/null 2>&1; then
  echo "[install] WARNING: tesseract binary not found. Fine/location need OCR."
  echo "[install]   Debian/Ubuntu: sudo apt install tesseract-ocr"
  echo "[install]   macOS:         brew install tesseract"
fi

# --- 3. build the command (absolute paths, quoted) -------------------------
CMD="$PY $TRACK --plate ${PLATES[*]} --state-dir $STATE_DIR"
if [ "${#EMAILS[@]}" -gt 0 ]; then
  CMD="$CMD --email-to ${EMAILS[*]}"
fi
LOG="$STATE_DIR/run.log"

# Cron runs current code: pull latest before the tracker. --ff-only means a
# pull can only fast-forward — if the checkout ever diverges it fails cleanly
# instead of making a merge commit. It's joined with ';' (not '&&') so a pull
# hiccup (network blip, divergence) never blocks the weekly report: the tracker
# still runs on the last-known-good checkout. Both halves share one log via {}.
CRON_CMD="{ cd $REPO_DIR && $GIT pull --ff-only; $CMD; } >> $LOG 2>&1"

# --- 4. prime the OCR cache so the first cron run is fast ------------------
mkdir -p "$STATE_DIR"
echo "[install] priming OCR cache (first run downloads + OCRs each PDF once) ..."
$PY "$TRACK" --plate "${PLATES[@]}" --state-dir "$STATE_DIR" --dry-run >/dev/null 2>&1 || \
  echo "[install] (cache prime skipped/failed — not fatal)"

# --- 5. install cron -------------------------------------------------------
if [ "$INSTALL_CRON" -eq 1 ]; then
  echo "[install] installing cron: $SCHEDULE"
  TMP="$(mktemp)"
  # Preserve existing crontab, dropping (a) any previously-managed line and
  # (b) any older, unmarked line that runs THIS repo's track.py — so a prior
  # hand-installed cron doesn't survive as a duplicate.
  crontab -l 2>/dev/null | grep -vF "$MARKER" | grep -vF "$TRACK" > "$TMP" || true
  {
    echo "$MARKER"
    echo "$SCHEDULE $CRON_CMD  $MARKER"
  } >> "$TMP"
  crontab "$TMP"
  rm -f "$TMP"
  echo "[install] cron installed. Current entries:"
  crontab -l | grep -F "$MARKER" | grep -v "^$MARKER\$"
else
  echo "[install] --no-cron: skipping cron install."
  echo "[install] to run manually: $CMD"
fi

echo "[install] done."
