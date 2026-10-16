#!/usr/bin/env bash
#
# deploy.sh — sync the robot workspace source to the Raspberry Pi over SSH/rsync.
#
# Usage:
#   ./deploy.sh                 # dry-run disabled, syncs src/ to the Pi
#   ./deploy.sh --dry-run       # show what would transfer without changing anything
#   ./deploy.sh --build         # sync, then run `colcon build` on the Pi
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

# Local directory that gets synced (the ROS workspace source tree).
LOCAL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/src/"
REMOTE_DEST="${RPI_USER}@${RPI_HOST}:${RPI_PATH}/src/"

# ---- Flags ------------------------------------------------------------------
DRY_RUN=0
DO_BUILD=0
DO_RESTART=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --build)   DO_BUILD=1 ;;
    --restart) DO_RESTART=1 ;;
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

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo ">> Dry run complete."
  exit 0
fi

# ---- Optional remote steps --------------------------------------------------
if [[ "$DO_BUILD" -eq 1 ]]; then
  echo ">> Running colcon build on ${RPI_HOST}"
  ssh "${RPI_USER}@${RPI_HOST}" "cd ${RPI_PATH} && colcon build --symlink-install"
fi

if [[ "$DO_RESTART" -eq 1 ]]; then
  echo ">> Restarting ${RPI_SERVICE} on ${RPI_HOST}"
  ssh "${RPI_USER}@${RPI_HOST}" "sudo systemctl restart ${RPI_SERVICE}"
fi

echo ">> Done."
