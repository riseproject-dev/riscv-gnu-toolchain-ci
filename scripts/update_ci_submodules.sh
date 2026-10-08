#!/usr/bin/env bash
# Adapted from riscv-collab/riscv-gnu-toolchain#1891. Keep full history for
# postcommit's previous-result lookup; only the mirrors and retry policy change.
set -euo pipefail

if [ "$#" -eq 0 ]; then
    echo "Usage: bash scripts/update_ci_submodules.sh SUBMODULE..." >&2
    exit 2
fi

export GIT_TERMINAL_PROMPT=0

# Existing .git/config (including restored caches) may still contain old URLs.
git submodule sync --recursive -- "$@"

for attempt in 1 2 3 4 5; do
    # Retry the entire resumable operation: successful checkouts are reused.
    # Never use --remote: each submodule must stay at its recorded gitlink SHA.
    if git submodule update --init --recursive -- "$@"; then
        exit 0
    fi
    if [ "$attempt" -lt 5 ]; then
        delay=$((attempt * 30))
        echo "Submodule checkout failed (attempt $attempt/5); retrying in ${delay}s" >&2
        sleep "$delay"
    fi
done

echo "Submodule checkout failed after 5 attempts" >&2
exit 1
