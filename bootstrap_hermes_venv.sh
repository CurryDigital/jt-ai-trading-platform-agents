#!/bin/bash
# bootstrap_hermes_venv.sh
# =========================
# Idempotent provisioning of the Hermes ETL Python virtualenv.
#
# Run this on the host that executes daily_refresh.sh. It:
#   1. Locates the Hermes venv (defaults to ~/.hermes/hermes-agent/venv)
#   2. Verifies the venv exists; creates it from system python3 if not
#   3. Upgrades pip + setuptools + wheel
#   4. Installs everything in agents/etl/requirements.txt
#   5. Smoke-tests the imports the daily cron actually needs
#   6. Optionally provisions a second profile (qr_etl) for shadow runs
#
# Designed to be safe to re-run. Use --check to validate without installing.
#
# Exit codes:
#   0  — venv is good
#   64 — usage error (bad args)
#   65 — venv directory unwriteable or system python3 missing
#   70 — install failed
#   71 — smoke test failed after install (genuine bug — escalate)

set -uo pipefail

# ── Defaults (override via env vars) ─────────────────────────────────────
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
VENV_DIR="${HERMES_VENV:-$HERMES_HOME/hermes-agent/venv}"
PROFILE_VENV_DIR="${HERMES_PROFILE_VENV:-$HERMES_HOME/profiles/qr_etl/venv}"
REQUIREMENTS="${ETL_REQUIREMENTS:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/agents/etl/requirements.txt}"
CHECK_ONLY=false
INSTALL_PROFILE_VENV=false

# ── Argparse ─────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)            CHECK_ONLY=true; shift ;;
        --with-profile-venv) INSTALL_PROFILE_VENV=true; shift ;;
        --venv)             VENV_DIR="$2"; shift 2 ;;
        --requirements)     REQUIREMENTS="$2"; shift 2 ;;
        -h|--help)
            grep -E '^#( |$)' "$0" | sed 's/^# //; s/^#//'
            exit 0 ;;
        *)
            echo "Unknown arg: $1" >&2
            echo "Usage: $0 [--check] [--with-profile-venv] [--venv PATH] [--requirements PATH]" >&2
            exit 64 ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────────
log() {
    printf '[bootstrap_hermes_venv] %s\n' "$*"
}

fail() {
    log "FAIL: $*"
    exit "$2"
}

smoke_test() {
    local py="$1"
    log "Smoke test: $py -c 'import psycopg2, dotenv, pandas, numpy'"
    "$py" -c "
import sys
mods = ['psycopg2', 'dotenv', 'pandas', 'numpy', 'requests', 'sklearn', 'hmmlearn']
missing = []
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        missing.append(f'{m}: {e}')
if missing:
    print('MISSING:')
    for x in missing:
        print(' ', x)
    sys.exit(1)
print('OK — all required imports succeed')
" || return 1
    return 0
}

provision_venv() {
    local venv="$1"
    if [[ -x "$venv/bin/python3" ]]; then
        log "Found existing venv: $venv"
        return 0
    fi
    log "Creating venv at $venv"
    mkdir -p "$(dirname "$venv")" || fail "cannot mkdir $(dirname "$venv")" 65
    python3 -m venv "$venv" || fail "python3 -m venv failed (check system python3-venv package)" 65
}

install_deps() {
    local venv="$1"
    log "Upgrading pip / setuptools / wheel in $venv"
    "$venv/bin/python3" -m pip install --quiet --upgrade pip setuptools wheel \
        || fail "pip upgrade failed" 70

    if [[ ! -f "$REQUIREMENTS" ]]; then
        log "Requirements file not found at $REQUIREMENTS — installing minimum set"
        "$venv/bin/python3" -m pip install --quiet \
            psycopg2-binary python-dotenv pandas numpy requests \
            scikit-learn hmmlearn boto3 \
            || fail "minimum-set install failed" 70
    else
        log "Installing from $REQUIREMENTS"
        "$venv/bin/python3" -m pip install --quiet -r "$REQUIREMENTS" \
            || fail "pip install -r failed" 70
        # Belt-and-braces: ensure psycopg2-binary and python-dotenv are present
        # even if requirements.txt names them differently or pins them oddly.
        "$venv/bin/python3" -m pip install --quiet psycopg2-binary python-dotenv \
            || fail "psycopg2-binary / python-dotenv install failed" 70
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────
log "Hermes venv:           $VENV_DIR"
log "Requirements:          $REQUIREMENTS"
log "Profile-venv extra:    $INSTALL_PROFILE_VENV (path: $PROFILE_VENV_DIR)"
log "Mode:                  $([ "$CHECK_ONLY" == true ] && echo check-only || echo install)"

if [[ "$CHECK_ONLY" == true ]]; then
    if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
        fail "venv not found at $VENV_DIR" 65
    fi
    if smoke_test "$VENV_DIR/bin/python3"; then
        log "✅ Hermes venv is healthy."
        exit 0
    else
        fail "smoke test failed — run without --check to repair" 71
    fi
fi

# Provision and install
provision_venv "$VENV_DIR"
install_deps "$VENV_DIR"

if ! smoke_test "$VENV_DIR/bin/python3"; then
    fail "post-install smoke test failed — investigate" 71
fi

if [[ "$INSTALL_PROFILE_VENV" == true ]]; then
    log "Provisioning shadow profile venv at $PROFILE_VENV_DIR"
    provision_venv "$PROFILE_VENV_DIR"
    install_deps "$PROFILE_VENV_DIR"
    smoke_test "$PROFILE_VENV_DIR/bin/python3" || fail "shadow profile smoke test failed" 71
fi

log "✅ Bootstrap complete. Daily cron can now run."
log "Verify with:  bash $0 --check"
