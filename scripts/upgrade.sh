#!/usr/bin/env bash
# ====================================================================
# AgentMesh Platform — One-Click Upgrade Script
# ====================================================================
# Performs a full platform upgrade: git pull, pip install, database
# migration, and provides rollback support on failure.
#
# Usage:
#   bash scripts/upgrade.sh                        # normal upgrade
#   bash scripts/upgrade.sh --dry-run              # preview only
#   bash scripts/upgrade.sh --rollback             # rollback to last backup
#   bash scripts/upgrade.sh --backup-dir /custom   # custom backup dir
#   bash scripts/upgrade.sh --venv /opt/venv       # custom venv path
#
# Rollback workflow:
#   1. Before upgrading, the script creates a backup of the DB and
#      records the current git commit (PREVIOUS_COMMIT).
#   2. If pip install or data migration fails, rollback restores the
#      DB from backup and reverts the working tree to PREVIOUS_COMMIT.
#   3. Manual rollback: bash scripts/upgrade.sh --rollback
# ====================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ─── Defaults ──────────────────────────────────────────────────────────
BACKUP_DIR="${PROJECT_ROOT}/backups"
VENV_DIR=""
DB_PATH="${PROJECT_ROOT}/agentmesh_platform.db"
ROLLBACK_FILE="${PROJECT_ROOT}/.upgrade_rollback"
DRY_RUN=false
ROLLBACK_MODE=false

# ─── Colors ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ─── Parse args ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)     DRY_RUN=true;        shift ;;
        --rollback)    ROLLBACK_MODE=true;  shift ;;
        --backup-dir)  BACKUP_DIR="$2";     shift 2 ;;
        --venv)        VENV_DIR="$2";       shift 2 ;;
        --db)          DB_PATH="$2";        shift 2 ;;
        --help)
            echo "Usage: $0 [--dry-run] [--rollback] [--backup-dir DIR] [--venv PATH] [--db PATH]"
            exit 0
            ;;
        *)  err "Unknown option: $1"; exit 1 ;;
    esac
done

# ─── Prerequisites ────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    err "git is required but not found."
    exit 1
fi

if ! git -C "$PROJECT_ROOT" rev-parse --git-dir &>/dev/null 2>&1; then
    err "Not a git repository: ${PROJECT_ROOT}"
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)
if [[ -z "$PYTHON" ]]; then
    err "Python 3 not found."
    exit 1
fi

PIP="${VENV_DIR}/bin/pip"
if [[ -z "$VENV_DIR" ]]; then
    PIP=$(command -v pip3 || command -v pip)
fi
if [[ -z "$PIP" ]] || ! command -v "$PIP" &>/dev/null; then
    err "pip not found. Use --venv to specify a virtual environment."
    exit 1
fi

# ═══════════════════════════════════════════════════════════════════════
# ROLLBACK MODE
# ═══════════════════════════════════════════════════════════════════════
if $ROLLBACK_MODE; then
    echo ""
    echo "╔═══════════════════════════════════════════════════╗"
    echo "║     AgentMesh Rollback                           ║"
    echo "╚═══════════════════════════════════════════════════╝"

    if [[ ! -f "$ROLLBACK_FILE" ]]; then
        err "No rollback state found (${ROLLBACK_FILE})."
        info "Nothing to roll back."
        exit 1
    fi

    # shellcheck source=/dev/null
    source "$ROLLBACK_FILE"

    echo "  Previous commit: ${PREVIOUS_COMMIT:-unknown}"
    echo "  Backup DB:       ${BACKUP_DB:-none}"
    echo "  Mode:            $($DRY_RUN && echo 'Preview' || echo 'Execute')"
    echo ""

    # Step R1: Restore database
    if [[ -n "${BACKUP_DB:-}" && -f "$BACKUP_DB" ]]; then
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo -e "${CYAN}R1${NC} Restore database from backup"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if $DRY_RUN; then
            info "Would restore: cp '${BACKUP_DB}' '${DB_PATH}'"
        else
            cp "$BACKUP_DB" "$DB_PATH"
            ok "Database restored from: ${BACKUP_DB}"
        fi
    else
        warn "No backup DB available — skipping DB restore."
    fi

    # Step R2: Revert git working tree
    if [[ -n "${PREVIOUS_COMMIT:-}" ]]; then
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo -e "${CYAN}R2${NC} Revert git to previous commit"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if $DRY_RUN; then
            info "Would run: git -C '${PROJECT_ROOT}' reset --hard '${PREVIOUS_COMMIT}'"
        else
            git -C "$PROJECT_ROOT" reset --hard "$PREVIOUS_COMMIT"
            ok "Reverted to commit: ${PREVIOUS_COMMIT}"
        fi
    else
        warn "No previous commit recorded — skipping git revert."
    fi

    # Step R3: Re-install packages (previous version)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}R3${NC} Reinstall packages"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if $DRY_RUN; then
        info "Would run: $PIP install -e '${PROJECT_ROOT}'"
    else
        "$PIP" install -e "$PROJECT_ROOT"
        ok "Packages reinstalled."
    fi

    # Cleanup rollback state
    if ! $DRY_RUN; then
        rm -f "$ROLLBACK_FILE"
        ok "Rollback complete."
    fi

    echo ""
    echo "╔═══════════════════════════════════════════════════╗"
    echo "║      Rollback completed                           ║"
    echo "╚═══════════════════════════════════════════════════╝"
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════════
# UPGRADE MODE
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║     AgentMesh One-Click Upgrade                   ║"
echo "╚═══════════════════════════════════════════════════╝"
echo "  Project:      ${PROJECT_ROOT}"
echo "  Python:       $($PYTHON --version 2>&1)"
echo "  Pip:          ${PIP}"
echo "  Backup dir:   ${BACKUP_DIR}"
echo "  DB path:      ${DB_PATH}"
echo "  Mode:         $($DRY_RUN && echo 'Preview (--dry-run)' || echo 'Execute')"
echo ""

CURRENT_COMMIT=$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
info "Current commit: ${CURRENT_COMMIT}"

# ── S1: Backup database ────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S1${NC} Backup database"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    info "Would create backup dir: mkdir -p ${BACKUP_DIR}"
    if [[ -f "$DB_PATH" ]]; then
        TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
        BACKUP_DB="${BACKUP_DIR}/agentmesh_platform_pre_upgrade_${TIMESTAMP}.db"
        info "Would backup: ${DB_PATH} -> ${BACKUP_DB}"
    else
        warn "No database found at ${DB_PATH} — skipping backup."
        BACKUP_DB=""
    fi
else
    mkdir -p "$BACKUP_DIR"
    BACKUP_DB=""
    if [[ -f "$DB_PATH" ]]; then
        TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
        BACKUP_DB="${BACKUP_DIR}/agentmesh_platform_pre_upgrade_${TIMESTAMP}.db"
        cp "$DB_PATH" "$BACKUP_DB"
        ok "Database backed up: ${BACKUP_DB}"
    else
        warn "No database found at ${DB_PATH} — skipping backup."
    fi
fi

# ── S2: Save rollback state ───────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S2${NC} Save rollback state"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    info "Would save to: ${ROLLBACK_FILE}"
    info "  PREVIOUS_COMMIT=${CURRENT_COMMIT}"
    info "  BACKUP_DB=${BACKUP_DB}"
else
    cat > "$ROLLBACK_FILE" <<EOF
PREVIOUS_COMMIT=${CURRENT_COMMIT}
BACKUP_DB=${BACKUP_DB:-}
DB_PATH=${DB_PATH}
EOF
    ok "Rollback state saved: ${ROLLBACK_FILE}"
fi

# ── S3: Git pull ──────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S3${NC} Git pull (fetch latest code)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    CURRENT_BRANCH=$(git -C "$PROJECT_ROOT" branch --show-current 2>/dev/null || echo "unknown")
    info "Would run: git -C '${PROJECT_ROOT}' pull origin '${CURRENT_BRANCH}'"
else
    CURRENT_BRANCH=$(git -C "$PROJECT_ROOT" branch --show-current 2>/dev/null || echo "main")
    git -C "$PROJECT_ROOT" pull origin "$CURRENT_BRANCH"
    ok "Git pull complete (branch: ${CURRENT_BRANCH})"
fi

# ── S4: Install / upgrade Python packages ─────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S4${NC} Install / upgrade Python packages"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    info "Would run: $PIP install -e '${PROJECT_ROOT}'"
    info "Would run: $PIP install -e '${PROJECT_ROOT}[dev]'"
else
    if "$PIP" install -e "$PROJECT_ROOT"; then
        ok "Core packages installed."
    else
        err "pip install failed."
        info "Run 'bash scripts/upgrade.sh --rollback' to revert."
        exit 1
    fi

    # Install dev extras if available
    "$PIP" install -e "${PROJECT_ROOT}[dev]" 2>/dev/null || true
fi

# ── S5: Data migration ────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S5${NC} Data migration (schema upgrade)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    info "Would run migration script if present."
    info "Looking for: ${PROJECT_ROOT}/scripts/migrate.py"
    info "Would run: $PYTHON scripts/migrate.py --db '${DB_PATH}'"
else
    MIGRATE_SCRIPT="${PROJECT_ROOT}/scripts/migrate.py"
    if [[ -f "$MIGRATE_SCRIPT" ]]; then
        if $PYTHON "$MIGRATE_SCRIPT" --db "$DB_PATH"; then
            ok "Data migration completed successfully."
        else
            err "Data migration FAILED."
            info "Rolling back..."
            bash "$0" --rollback
            exit 1
        fi
    else
        info "No migration script found (scripts/migrate.py) — skipping."
        info "The schema is applied on next startup via db_schema.init_db()."
    fi
fi

# ── S6: Verify ───────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S6${NC} Verify installation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    info "Would verify: $PYTHON -c 'import agentmesh; print(agentmesh.__version__)'"
else
    VERIFY_OUTPUT=$("$PYTHON" -c "import agentmesh; print(agentmesh.__version__)" 2>&1 || true)
    if [[ -n "$VERIFY_OUTPUT" ]]; then
        ok "AgentMesh version: ${VERIFY_OUTPUT}"
    else
        # Fallback: check if the package is importable
        if "$PYTHON" -c "import agentmesh; print('ok')" 2>/dev/null; then
            ok "AgentMesh package importable."
        else
            warn "Could not verify AgentMesh version (package may not export __version__)."
        fi
    fi
fi

# ── S7: Cleanup rollback state (success) ─────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S7${NC} Finalize (remove rollback state on success)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    info "Would remove rollback state: rm -f ${ROLLBACK_FILE}"
else
    rm -f "$ROLLBACK_FILE"
    ok "Rollback state cleared (upgrade succeeded)."
fi

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════╗"
if $DRY_RUN; then
    echo "║      Preview complete — no actual changes made   ║"
    echo "║      Remove --dry-run to execute upgrade         ║"
else
    echo "║      Upgrade complete                             ║"
fi
echo "╚═══════════════════════════════════════════════════╝"
echo ""
echo "  Previous commit: ${CURRENT_COMMIT}"
echo "  New commit:      $(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || echo '?')"
echo "  Database:        ${DB_PATH}"
echo "  Backup:          ${BACKUP_DB:-none}"
echo ""

if ! $DRY_RUN; then
    info "To roll back: bash scripts/upgrade.sh --rollback"
    info "(Rollback is only available if upgrade state file still exists.)"
fi
