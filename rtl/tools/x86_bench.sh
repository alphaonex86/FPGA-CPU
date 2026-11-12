#!/bin/bash
# Usage: [L1I_KB=16] [L1D_KB=16] [L2_KB=256] rtl/tools/x86_bench.sh "<the architectural change or optimisation measured>"
# The benchmark set of the project's own core (rtl/x86; not the C2 Mu or any other external CPU),
# tick limited: each program of BENCH loops forever (its main called again and again) and runs
# exactly TICKS cycles on the core model built with the given cache sizes (+mem_lat=10); its score
# is the IPC over them (instructions retired / TICKS), the trace checked against Unicorn. b_l1,
# b_l2 and b_ram (tests/x86/bench/b_mem.c) take their working set from the sizes: half the L1D,
# half the L2, twice the L2. A program the core cannot run yet (an unsupported instruction: x87
# before M6) scores n/a. Appends one row to plan/bench_history.md (date, commit, cache sizes, note,
# IPC per program, the geometric mean of those that ran). Changing TICKS, BENCH or the memory model
# starts a new table there: rows are only comparable within one.
set -eu
note=${1:?usage: [L1I_KB=16] [L1D_KB=16] [L2_KB=256] x86_bench.sh \"<the change or optimisation measured>\"}
L1I_KB=${L1I_KB:-16} L1D_KB=${L1D_KB:-16} L2_KB=${L2_KB:-256}
TICKS=1000000
BENCH=(c5_coremark c1_mix c2_core c3_string c4_bits b_l1 b_l2 b_ram b_fpu)
(( 2 * L2_KB <= 3072 )) || { echo "L2_KB=$L2_KB: b_ram (twice the L2) does not fit the 3 MB above 1 MB of core_top" >&2; exit 1; }
cd "$(dirname "$0")/.."
out=build/x86/bench
mkdir -p "$out"
. tools/x86_files.sh
nice -n 19 verilator --cc --exe --build -j 0 -Wall -Wno-UNUSEDSIGNAL --top-module core_top \
    -GL1I_KB="$L1I_KB" -GL1D_KB="$L1D_KB" -GL2_KB="$L2_KB" \
    --Mdir "$out/obj" "${X86_SRCS[@]}" tests/x86/tb/core_top.sv tests/x86/tb/core_tb.cpp -o core_tb > "$out/build.log" 2>&1 \
    || { grep -m20 -A3 "%Error\|%Warning" "$out/build.log"; exit 1; }
row="| $(date +%F) | $(git describe --always --dirty) | $L1I_KB / $L1D_KB / $L2_KB | ${note//|//} |"
logsum=0
ran=0
for b in "${BENCH[@]}"; do
    src=$out/bench_$b.c          # the program's main renamed, called in a loop
    case $b in
        b_l1)  prog=tests/x86/bench/b_mem.c; cflags="-O2 -DSIZE=$((L1D_KB * 512))" ;;
        b_l2)  prog=tests/x86/bench/b_mem.c; cflags="-O2 -DSIZE=$((L2_KB * 512))" ;;
        b_ram) prog=tests/x86/bench/b_mem.c; cflags="-O2 -DSIZE=$((L2_KB * 2048))" ;;
        *)     prog=tests/x86/$b.c
               [[ -f $prog ]] || prog=tests/x86/bench/$b.c
               cflags=$(sed -n 's|^// cflags: ||p' "$prog") ;;
    esac
    { echo "// cflags: ${cflags:--O2}"
      echo "#define main bench_main"
      echo "#include \"../../../$prog\""
      echo "#undef main"
      echo "int main(void) { for (;;) bench_main(); }"; } > "$src"
    tools/x86_test.sh "$src" > /dev/null
    python3 -I -c "import sys; d = open(sys.argv[1], 'rb').read(); open(sys.argv[2], 'w').write(''.join('%02x\n' % b for b in d))" \
        "build/x86/bench_$b.bin" "$out/$b.hex"
    if ! res=$("$out/obj/core_tb" "+image=$out/$b.hex" "+trace=$out/$b.trace" "+ticks=$TICKS" +mem_lat=10 2>&1); then
        [[ $res == *"FAIL unsupported instruction"* ]] || { echo "$b: $res"; exit 1; }
        echo "$b: n/a (an unsupported instruction)"
        row+=" n/a |"
        continue
    fi
    ext/x86_trace_check --partial "build/x86/bench_$b.bin" 1000 "$out/$b.trace" > /dev/null
    insns=${res%% *}
    ipc=$(awk -v i="$insns" -v t="$TICKS" 'BEGIN { printf "%.3f", i / t }')
    echo "$b: $insns instructions in $TICKS cycles, IPC $ipc"
    row+=" $ipc |"
    logsum=$(awk -v s="$logsum" -v x="$ipc" 'BEGIN { printf "%.9f", s + log(x) }')
    ran=$((ran + 1))
done
mean=$(awk -v s="$logsum" -v n="$ran" 'BEGIN { printf "%.3f", exp(s / n) }')
echo "geometric mean IPC $mean ($ran programs)"
echo "$row $mean |" >> ../plan/bench_history.md
