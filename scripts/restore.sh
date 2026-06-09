#!/usr/bin/env bash
# ====================================================================
# AgentMesh Platform — Database Restore Script
# ====================================================================
# Restores a SQLite database from a backup created by backup.sh.
# Supports listing available backups, restoring from latest symlink,
# or specifying an explicit backup file with --file.
#
# Usage:
#   bash scripts/restore.sh --list                    # list backups
#   bash scripts/restore.sh                           # restore latest
#   bash scripts/restore.sh --file backups/shop_20260609-143000.db
#   bash scripts/restore.sh --db /path/to/shop.db     # custom target
#   bash scripts/restore.sh --dry-run                 # preview only
#   bash scripts/restore.sh --backup                  # auto backup first
# ====================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ─── Defaults ──────────────────────────────────────────────────────────
DB_PATH="${PROJECT_ROOT}/agentmesh_platform.db"
BACKUP_DIR="${PROJECT_ROOT}/backups"
RESTORE_FILE=""       # explicit backup file
LIST_MODE=false
DRY_RUN=false
AUTO_BACKUP=false     # backup existing DB before restore

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
        --file)     RESTORE_FILE="$2";  shift 2 ;;
        --backup)   AUTO_BACKUP=true;   shift ;;
        --dry-run)  DRY_RUN=true;       shift ;;
        --list)     LIST_MODE=true;     shift ;;
        --help)
            echo "Usage: $0 [--db PATH] [--dir DIR] [--file BACKUP] [--backup] [--dry-run] [--list]"
            exit 0
            ;;
        *)  err "Unknown option: $1"; exit 1 ;;
    esac
done

# ─── List mode ─────────────────────────────────────────────────────────
if $LIST_MODE; then
    echo ""
    echo "╔═══════════════════════════════════════════════════╗"
    echo "║     Available Backups                             ║"
    echo "╚═══════════════════════════════════════════════════╝"
    echo ""
    if [[ -d "$BACKUP_DIR" ]]; then
        BACKUPS=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "*.db" ! -name "*_latest*" | sort -r)
        if [[ -z "$BACKUPS" ]]; then
            info "No backups found in ${BACKUP_DIR}"
        else
            echo "$BACKUPS" | while read -r f; do
                SIZE=$(du -sh "$f" | cut -f1)
                MTIME=$(stat -f "%Sm" "$f" 2>/dev/null || stat -c "%y" "$f" 2>/dev/null || echo "?")
                echo "  $(basename "$f")  (${SIZE}, ${MTIME})"
            done
        fi
        if [[ -L "${BACKUP_DIR}/"*_latest.db ]]; then
            LATEST=$(readlink "${BACKUP_DIR}/"*_latest.db)
            echo ""
            ok "Latest backup: $(basename "$LATEST")"
        fi
    else
        info "Backup directory does not exist: ${BACKUP_DIR}"
    fi
    exit 0
fi

# ─── Resolve restore source ────────────────────────────────────────────
if [[ -z "$RESTORE_FILE" ]]; then
    # Auto-detect latest backup via symlink or file list
    LATEST_LINK=$(find "$BACKUP_DIR" -maxdepth 1 -type l -name "*_latest.db" 2>/dev/null | head -1)
    if [[ -n "$LATEST_LINK" ]]; then
        RESTORE_FILE=$(readlink "$LATEST_LINK")
        if [[ "$RESTORE_FILE" != /* ]]; then
            RESTORE_FILE="$(dirname "$LATEST_LINK")/$RESTORE_FILE"
        fi
    else
        RESTORE_FILE=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "*.db" ! -name "*_latest*" -print 2>/dev/null | sort | tail -1)
    fi
fi

if [[ -z "$RESTORE_FILE" || ! -f "$RESTORE_FILE" ]]; then
    err "No backup file found. Use --list to see available backups, or --file to specify one."
    exit 1
fi

# ─── Main ──────────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║     AgentMesh Database Restore                    ║"
echo "╚═══════════════════════════════════════════════════╝"
echo "  Source (backup): ${RESTORE_FILE}"
echo "  Target (DB):     ${DB_PATH}"
echo "  Auto-backup:     ${AUTO_BACKUP}"
echo "  Mode:            $($DRY_RUN && echo 'Preview (--dry-run)' || echo 'Execute')"
echo ""

# ── Step 1: Backup existing DB (optional) ──────────────────────────────
if $AUTO_BACKUP; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}S1${NC} Backup existing database before restore"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if $DRY_RUN; then
        info "Would run: bash ${SCRIPT_DIR}/backup.sh --db '${DB_PATH}' --dir '${BACKUP_DIR}'"
    else
        bash "$SCRIPT_DIR/backup.sh" --db "$DB_PATH" --dir "$BACKUP_DIR"
        ok "Existing database backed up"
    fi
fi

# ── Step 2: Validate backup file ───────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S2${NC} Validate backup integrity"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SOURCE_SIZE=$(du -sh "$RESTORE_FILE" | cut -f1)
info "Backup size: ${SOURCE_SIZE}"

if $DRY_RUN; then
    info "Would run: sqlite3 '${RESTORE_FILE}' 'PRAGMA integrity_check;'"
else
    INTEGRITY=$(sqlite3 "$RESTORE_FILE" "PRAGMA integrity_check;" 2>&1)
    if [[ "$INTEGRITY" == "ok" ]]; then
        ok "Integrity check passed"
    else
        err "Backup integrity FAILED: ${INTEGRITY}"
        exit 1
    fi
fi

# ── Step 3: Perform restore ────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S3${NC} Restore database"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $DRY_RUN; then
    info "Would restore: sqlite3 '${DB_PATH}' '.restore '${RESTORE_FILE}''"
    warn "Existing database at ${DB_PATH} would be OVERWRITTEN"
    info "Use --backup to auto-backup first, or manually copy ${DB_PATH} for safety."
else
    # Warn user if DB exists
    if [[ -f "$DB_PATH" ]]; then
        warn "Overwriting existing database: ${DB_PATH}"
    fi

    sqlite3 "$DB_PATH" ".restore '${RESTORE_FILE}'"
    ok "Restore complete: ${RESTORE_FILE} → ${DB_PATH}"
fi

# ── Summary ────────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════╗"
if $DRY_RUN; then
    echo "║      Preview complete — no actual changes made   ║"
    echo "║      Remove --dry-run to execute restore         ║"
else
    echo "║      Restore complete                             ║"
fi
echo "╚═══════════════════════════════════════════════════╝"
echo ""
echo "  Source:  ${RESTORE_FILE}"
echo "  Target:  ${DB_PATH}"
echo ""
info "Verify with: python -c \"import sqlite3; c=sqlite3.connect('${DB_PATH}'); c.execute('SELECT COUNT(*) FROM sqlite_master'); print(c.fetchone())\""
