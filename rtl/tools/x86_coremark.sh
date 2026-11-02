#!/bin/bash
# Usage: rtl/tools/x86_coremark.sh
# CoreMark on the x86_core model (ideal memory): runs 1 and 2 iterations of
# tests/x86/c5_coremark.c, both checked against Unicorn; their difference is
# one iteration without the setup: prints its cycles and CoreMark/MHz.
set -eu
cd "$(dirname "$0")/.."
mkdir -p build/x86
two=build/x86/c5_coremark2.c
sed 's/-DITERATIONS=1/-DITERATIONS=2/' tests/x86/c5_coremark.c > "$two"
grep -q -- "-DITERATIONS=2" "$two" || { echo "no -DITERATIONS=1 in tests/x86/c5_coremark.c"; exit 1; }
log=$(tools/x86_core_test.sh tests/x86/c5_coremark.c "$two")
echo "$log"
echo "$log" | awk 'BEGIN {n = 0} /instructions in/ {i[n] = $1; c[n++] = $4}
    END {
        if (n != 2) { print "expected 2 runs"; exit 1 }
        printf "one iteration: %d instructions, %d cycles, IPC %.3f, CoreMark/MHz %.3f\n",
               i[1] - i[0], c[1] - c[0], (i[1] - i[0]) / (c[1] - c[0]), 1e6 / (c[1] - c[0])
    }'
