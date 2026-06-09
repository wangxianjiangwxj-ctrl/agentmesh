#!/usr/bin/env bash
# ====================================================================
# AgentMesh Platform — Database Backup Script
# ====================================================================
# Backs up the SQLite database using sqlite3 .backup and auto-cleans
# backups older than RETENTION_DAYS (default: 7).
#
# Usage:
#   bash scripts/backup.sh                                # default config
#   bash scripts/backup.sh --db /path/to/shop.db          # custom DB path
#   bash scripts/backup.sh --dir /var/lib/agentmesh/backups
#   bash scripts/backup.sh --retain 14                    # keep 14 days
#   bash scripts/backup.sh --dry-run                      # preview only
# ====================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ─── Defaults ──────────────────────────────────────────────────────────
DB_PATH="${PROJECT_ROOT}/agentmesh_platform.db"
BACKUP_DIR="${PROJECT_ROOT}/backups"
RETENTION_DAYS=7
DRY_RUN=false

# ─── Colors ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ─── Parse args ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)       DB_PATH="$2";       shift 2 ;;
        --dir)      BACKUP_DIR="$2";    shift 2 ;;
        --retain)   RETENTION_DAYS="$2"; shift 2 ;;
        --dry-run)  DRY_RUN=true;       shift ;;
        --help)
            echo "Usage: $0 [--db PATH] [--dir DIR] [--retain DAYS] [--dry-run]"
            exit 0
            ;;
        *)  err "Unknown option: $1"; exit 1 ;;
    esac
done

# ─── Validate ──────────────────────────────────────────────────────────
if [[ ! -f "$DB_PATH" ]]; then
    err "Database not found: ${DB_PATH}"
    info "Use --db to specify the correct path."
    exit 1
fi

if ! command -v sqlite3 &>/dev/null; then
    err "sqlite3 CLI not found. Install it (e.g. apt install sqlite3, brew install sqlite3)."
    exit 1
fi

# ─── Main ──────────────────────────────────────────────────────────────
TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
DB_FILENAME=$(basename "$DB_PATH")
BACKUP_FILE="${BACKUP_DIR}/${DB_FILENAME%.*}_${TIMESTAMP}.db"
LATEST_LINK="${BACKUP_DIR}/${DB_FILENAME%.*}_latest.db"

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║     AgentMesh Database Backup                     ║"
echo "╚═══════════════════════════════════════════════════╝"
echo "  Source:       ${DB_PATH}"
echo "  Backup dir:   ${BACKUP_DIR}"
echo "  Retention:    ${RETENTION_DAYS} days"
echo "  Mode:         $($DRY_RUN && echo 'Preview (--dry-run)' || echo 'Execute')"
echo ""

# ── Step 1: Create backup directory ────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S1${NC} Create backup directory"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if $DRY_RUN; then
    info "Would create: mkdir -p ${BACKUP_DIR}"
else
    mkdir -p "$BACKUP_DIR"
    ok "Backup directory ready: ${BACKUP_DIR}"
fi

# ── Step 2: Verify DB integrity ────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S2${NC} Verify DB integrity"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
DB_SIZE=$(du -sh "$DB_PATH" | cut -f1)
info "Database size: ${DB_SIZE}"

if $DRY_RUN; then
    info "Would run: sqlite3 '${DB_PATH}' 'PRAGMA integrity_check;'"
else
    INTEGRITY=$(sqlite3 "$DB_PATH" "PRAGMA integrity_check;" 2>&1)
    if [[ "$INTEGRITY" == "ok" ]]; then
        ok "Integrity check passed"
    else
        err "Integrity check FAILED: ${INTEGRITY}"
        exit 1
    fi
fi

# ── Step 3: Perform backup ─────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S3${NC} Perform backup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    info "Would backup to: ${BACKUP_FILE}"
    info "Would update symlink: ${LATEST_LINK} -> ${BACKUP_FILE}"
else
    # Use .backup command (safe, no exclusive lock required)
    sqlite3 "$DB_PATH" ".backup '${BACKUP_FILE}'"

    # Create / update latest symlink
    ln -sf "$BACKUP_FILE" "$LATEST_LINK"

    BACKUP_SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
    ok "Backup created: ${BACKUP_FILE} (${BACKUP_SIZE})"
    ok "Latest symlink: ${LATEST_LINK}"
fi

# ── Step 4: Clean old backups ──────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S4${NC} Clean backups older than ${RETENTION_DAYS} days"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    OLD_FILES=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "${DB_FILENAME%.*}_*.db" -mtime +$((RETENTION_DAYS - 1)) 2>/dev/null || true)
    if [[ -n "$OLD_FILES" ]]; then
        info "Would delete:"
        echo "$OLD_FILES" | while read -r f; do
            echo "  - $f ($(du -sh "$f" | cut -f1))"
        done
    else
        info "No expired backups to clean."
    fi
else
    DELETED_COUNT=0
    while IFS= read -r -d '' OLD_FILE; do
        rm -f "$OLD_FILE"
        info "Deleted old backup: ${OLD_FILE}"
        DELETED_COUNT=$((DELETED_COUNT + 1))
    done < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name "${DB_FILENAME%.*}_*.db" -mtime +$((RETENTION_DAYS - 1)) -print0 2>/dev/null || true)

    if [[ $DELETED_COUNT -eq 0 ]]; then
        info "No expired backups to clean."
    else
        ok "Cleaned ${DELETED_COUNT} expired backup(s)."
    fi
fi

# ── Summary ────────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════╗"
if $DRY_RUN; then
    echo "║      Preview complete — no actual changes made   ║"
    echo "║      Remove --dry-run to execute backup          ║"
else
    echo "║      Backup complete                             ║"
fi
echo "╚═══════════════════════════════════════════════════╝"
echo ""
echo "  Source:      ${DB_PATH}"
echo "  Backup:      ${BACKUP_FILE}"
echo "  Link:        ${LATEST_LINK}"
echo "  Retention:   ${RETENTION_DAYS} days"

# List current backups
echo ""
info "Current backups:"
ls -lh "$BACKUP_DIR"/"${DB_FILENAME%.*}"_*.db 2>/dev/null || echo "  (none)"
