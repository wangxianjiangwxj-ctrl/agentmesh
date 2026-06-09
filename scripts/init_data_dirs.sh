#!/usr/bin/env bash
# ====================================================================
# AgentMesh Platform — Initialize Production Data Directories
# ====================================================================
# Creates the standard directory layout for persistent data, logs,
# and backups. Designed to be run during deployment (Dockerfile,
# cloud-init, or manually on the host).
#
# Usage:
#   sudo bash scripts/init_data_dirs.sh
#
# Directories created:
#   /var/lib/agentmesh/data   — SQLite database and persistent state
#   /var/lib/agentmesh/logs   — Application log files (JSON rotation)
#   /var/lib/agentmesh/backups — Database dump / snapshot backups
# ====================================================================

set -euo pipefail

BASE_DIR="/var/lib/agentmesh"
USER="agentmesh"
GROUP="agentmesh"

echo "AgentMesh: Initializing data directories under ${BASE_DIR}..."

# ── Create dedicated system user (if not exists) ───────────────────────
if ! id -u "${USER}" >/dev/null 2>&1; then
    echo "Creating system user '${USER}'..."
    if command -v useradd >/dev/null 2>&1; then
        # Linux
        useradd --system --no-create-home --shell /usr/sbin/nologin "${USER}"
    elif command -v adduser >/dev/null 2>&1; then
        # Alpine / busybox
        adduser -S -H -s /sbin/nologin "${USER}"
    else
        echo "WARNING: Cannot create user '${USER}'. Create it manually:"
        echo "  sudo useradd --system --no-create-home ${USER}"
    fi
else
    echo "User '${USER}' already exists."
fi

# ── Create directories with correct permissions ────────────────────────
DIRS=(
    "${BASE_DIR}/data"
    "${BASE_DIR}/logs"
    "${BASE_DIR}/backups"
)

for dir in "${DIRS[@]}"; do
    if [ ! -d "${dir}" ]; then
        echo "  Creating ${dir}..."
        mkdir -p "${dir}"
    else
        echo "  ${dir} already exists."
    fi
    # Ensure correct ownership and permissions
    chown "${USER}:${GROUP}" "${dir}"
    chmod 750 "${dir}"
done

echo ""
echo "Done. Summary:"
echo "  ${BASE_DIR}/data     — 750, owner ${USER}:${GROUP}"
echo "  ${BASE_DIR}/logs     — 750, owner ${USER}:${GROUP}"
echo "  ${BASE_DIR}/backups  — 750, owner ${USER}:${GROUP}"
echo ""
echo "To verify:"
echo "  ls -la ${BASE_DIR}/"
