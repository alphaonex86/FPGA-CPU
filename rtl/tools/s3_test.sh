#!/bin/bash
# Usage: rtl/tools/s3_test.sh <test.S | test.c>...
# M8 (plan/x86_core.md): x86_core_test.sh with the memory behind the Socket 3 bus: s3_bus against
# FPGAcommon's chipset front end (rtl/tests/s3/cpu486_bif.v, copied from FPGAcommon/rtl/cpu486),
# each test at host latencies 0, 1 and 3; the retire trace checked against Unicorn.
set -eu
tests=()
for t; do tests+=("$(realpath "$t")"); done
cd "$(dirname "$0")/.."
out=build/s3
mkdir -p "$out"
. tools/x86_files.sh
echo '`verilator_config' > "$out/waive.vlt"
echo 'lint_off -file "*/cpu486_bif.v"' >> "$out/waive.vlt"
nice -n 19 verilator --cc --exe --build -j 4 -Wall -Wno-UNUSEDSIGNAL -Wno-PINCONNECTEMPTY -DS3_BUS --top-module core_top \
    --Mdir "$out/obj" "$out/waive.vlt" "${X86_SRCS[@]}" s3/s3_bus.sv tests/s3/cpu486_bif.v tests/x86/tb/core_top.sv \
    tests/x86/tb/core_tb.cpp -o core_tb > "$out/build.log" 2>&1 || { grep -m20 -A3 "%Error\|%Warning" "$out/build.log"; exit 1; }
rc=0
for t in "${tests[@]}"; do
    name=$(basename "${t%.*}")
    tools/x86_test.sh "$t" > /dev/null   # assembles build/x86/<name>.bin
    python3 -I -c "import sys; d = open(sys.argv[1], 'rb').read(); open(sys.argv[2], 'w').write(''.join('%02x\n' % b for b in d))" \
        "build/x86/$name.bin" "$out/$name.hex"
    for lat in 0 1 3; do
        echo "== $name, host latency $lat"
        if "$out/obj/core_tb" "+image=$out/$name.hex" "+trace=$out/$name.trace" "+host_lat=$lat" +max=20000000 +stats | grep -v "^stats: [^m]"; then
            tools/x86_test.sh "$t" "$out/$name.trace" || rc=1
        else
            rc=1
        fi
    done
done
exit $rc
