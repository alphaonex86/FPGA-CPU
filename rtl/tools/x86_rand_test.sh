#!/bin/bash
# Usage: rtl/tools/x86_rand_test.sh <count> [first seed]
# Runs <count> random programs (x86_rand.py) through x86_core_test.sh;
# prints only failures and the summary.
set -eu
count=$1
seed=${2:-1}
cd "$(dirname "$0")/.."
dir=build/x86/rand
mkdir -p "$dir"
files=()
for ((s = seed; s < seed + count; s++)); do
    python3 -I tools/x86_rand.py "$s" "$dir/r$s.S"
    files+=("$dir/r$s.S")
done
log=$dir/run.log
if X86_CORE_OUT=$dir/core tools/x86_core_test.sh "${files[@]}" > "$log" 2>&1; then rc=0; else rc=1; fi
grep -B2 -i "fail\|line [0-9]*:" "$log" | head -40 || true
echo "$(grep -c '^PASS' "$log") / $count PASS, cycles $(awk '/IPC/ {i += $1; c += $4} END {printf "%d, IPC %.3f", c, i / c}' "$log")"
exit $rc
