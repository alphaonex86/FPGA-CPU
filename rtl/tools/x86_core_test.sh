#!/bin/bash
# Usage: rtl/tools/x86_core_test.sh <test.S>...
# M2 (plan/x86_core.md): runs each flat 32-bit test on the x86_core
# Verilator model (rtl/tests/x86/tb/core_top.sv) and checks its retire
# trace against Unicorn instruction by instruction (x86_test.sh).
set -eu
tests=()
for t; do tests+=("$(realpath "$t")"); done
cd "$(dirname "$0")/.."
out=${X86_CORE_OUT:-build/x86/core}   # model + traces (x86_rand_test.sh: its own)
mkdir -p "$out"
. tools/x86_files.sh
nice -n 19 verilator --cc --exe --build -j 0 -Wall -Wno-UNUSEDSIGNAL --top-module core_top \
    --Mdir "$out/obj" "${X86_SRCS[@]}" tests/x86/tb/core_top.sv tests/x86/tb/core_tb.cpp -o core_tb > "$out/build.log" 2>&1 || { grep -m20 -A3 "%Error\|%Warning" "$out/build.log"; exit 1; }
rc=0
for t in "${tests[@]}"; do
    name=$(basename "${t%.*}")
    tools/x86_test.sh "$t" > /dev/null   # assembles build/x86/<name>.bin
    python3 -I -c "import sys; d = open(sys.argv[1], 'rb').read(); open(sys.argv[2], 'w').write(''.join('%02x\n' % b for b in d))" \
        "build/x86/$name.bin" "$out/$name.hex"
    echo "== $name"
    # shellcheck disable=SC2086   # X86_TB_ARGS: extra plusargs, e.g. "+stats +mem_lat=20"
    # second pass: FLUSH# every 20011 clocks and a snoop every 13 must not change the trace
    for extra in "" "+flush=20011 +snoop=13"; do
        if "$out/obj/core_tb" "+image=$out/$name.hex" "+trace=$out/$name.trace" ${X86_TB_ARGS:-} $extra; then
            tools/x86_test.sh "$t" "$out/$name.trace" || rc=1
        else
            rc=1
        fi
    done
done
exit $rc
