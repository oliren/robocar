#!/usr/bin/env bash
#
# deploy.sh — sync the robot workspace source to the Raspberry Pi over SSH/rsync.
#
# Usage:
#   ./deploy.sh                 # dry-run disabled, syncs src/ to the Pi
#   ./deploy.sh --dry-run       # show what would transfer without changing anything
#   ./deploy.sh --build         # sync, then run `colcon build` on the Pi
#   ./deploy.sh --systemd       # also sync systemd/ and (re)install the unit
#   ./deploy.sh --restart       # sync, then restart the robot systemd service
#
# Override defaults with env vars, e.g.:
#   RPI_HOST=other-pi RPI_USER=pi ./deploy.sh

set -euo pipefail

# ---- Config (override via environment) --------------------------------------
RPI_HOST="${RPI_HOST:-rpi-robot}"
RPI_USER="${RPI_USER:-oliren}"
RPI_PATH="${RPI_PATH:-~/robot_ws}"
# systemd service to restart with --restart (adjust to your setup).
RPI_SERVICE="${RPI_SERVICE:-robot_car.service}"

# Workspace root (local) and the directories that get synced.
LOCAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SRC="${LOCAL_ROOT}/src/"
LOCAL_SYSTEMD="${LOCAL_ROOT}/systemd/"
REMOTE_DEST="${RPI_USER}@${RPI_HOST}:${RPI_PATH}/src/"
REMOTE_SYSTEMD="${RPI_USER}@${RPI_HOST}:${RPI_PATH}/systemd/"

# Name of the unit file inside systemd/ and where it installs on the Pi.
SYSTEMD_UNIT="robot_car.service"
SYSTEMD_DEST="/etc/systemd/system/${SYSTEMD_UNIT}"

# ---- Flags ------------------------------------------------------------------
DRY_RUN=0
DO_BUILD=0
DO_RESTART=0
DO_SYSTEMD=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --build)   DO_BUILD=1 ;;
    --restart) DO_RESTART=1 ;;
    --systemd) DO_SYSTEMD=1 ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Run with --help for usage." >&2
      exit 1
      ;;
  esac
done

# ---- rsync ------------------------------------------------------------------
# -a  archive (perms, times, symlinks)
# -v  verbose
# -z  compress in transit
# --delete  remove remote files no longer present locally
# Excludes build artifacts and local-only cruft.
RSYNC_OPTS=(
  -avz
  --delete
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.git/'
  --exclude 'build/'
  --exclude 'install/'
  --exclude 'log/'
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC_OPTS+=(--dry-run)
  echo ">> DRY RUN — no files will be changed"
fi

echo ">> Syncing ${LOCAL_SRC}"
echo ">>      to ${REMOTE_DEST}"
rsync "${RSYNC_OPTS[@]}" "${LOCAL_SRC}" "${REMOTE_DEST}"

# A unit change should be installed on restart, so --restart implies --systemd.
if [[ "$DO_RESTART" -eq 1 ]]; then
  DO_SYSTEMD=1
fi

if [[ "$DO_SYSTEMD" -eq 1 ]]; then
  echo ">> Syncing ${LOCAL_SYSTEMD}"
  echo ">>      to ${REMOTE_SYSTEMD}"
  rsync "${RSYNC_OPTS[@]}" "${LOCAL_SYSTEMD}" "${REMOTE_SYSTEMD}"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo ">> Dry run complete."
  exit 0
fi

# Install the unit into /etc and reload systemd. Needs root on the Pi, so this
# is a separate sudo step (rsync runs as ${RPI_USER} and can't write /etc).
if [[ "$DO_SYSTEMD" -eq 1 ]]; then
  echo ">> Installing ${SYSTEMD_UNIT} on ${RPI_HOST}"
  # -t allocates a TTY so sudo can prompt for a password interactively.
  # (No prompt appears if oliren has a NOPASSWD sudoers rule — see systemd/README.md.)
  ssh -t "${RPI_USER}@${RPI_HOST}" \
    "sudo cp ${RPI_PATH}/systemd/${SYSTEMD_UNIT} ${SYSTEMD_DEST} && sudo systemctl daemon-reload"
fi

# ---- Optional remote steps --------------------------------------------------
if [[ "$DO_BUILD" -eq 1 ]]; then
  echo ">> Running colcon build on ${RPI_HOST}"
  ssh "${RPI_USER}@${RPI_HOST}" "cd ${RPI_PATH} && colcon build --symlink-install"
fi

if [[ "$DO_RESTART" -eq 1 ]]; then
  echo ">> Restarting ${RPI_SERVICE} on ${RPI_HOST}"
  ssh -t "${RPI_USER}@${RPI_HOST}" "sudo systemctl restart ${RPI_SERVICE}"
fi

echo ">> Done."
