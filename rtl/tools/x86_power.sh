#!/bin/bash
# Usage: rtl/tools/x86_power.sh "<the change measured>" [program...]
# Run it in claude-route.slice, after rtl/tools/x86_bench.sh (it takes that run's programs) and a full
# socket 3 build of the same RTL (rtl/s3/build.sh rtl/build/s3; placed and routed is enough).
# Power of the project's own core per workload: each program's measured window (after its warm-up) is
# dumped as a VCD from the core model (CYCLES cycles at the core clock CORE_NS), folded onto the
# netlist's names (tools/vcd_scope.py) and read by the Quartus Power Analyzer on that build: every
# register it can match takes its toggle rate from the program, the rest is propagated. Appends one
# row to plan/power_history.md: per program the total power (W) and the energy per instruction (nJ:
# total power / (clock x IPC of the window)). Default programs: one per benchmark group.
set -euo pipefail
note=${1:?usage: x86_power.sh \"<the change measured>\" [program...]}
shift
progs=("$@")
(( ${#progs[@]} )) || progs=(coremark-full interp-full hash-full lat_1m bw_64k code_87k phase ilp branch)
CYCLES=${CYCLES:-2000}
CORE_NS=${CORE_NS:-30}
QUARTUS=${QUARTUS:-$HOME/altera_lite/25.1std/quartus/bin}
cd "$(dirname "$0")/.."
bench=build/x86/bench
out=build/x86/power
proj=build/s3
hist=../plan/power_history.md
. tools/x86_files.sh
[[ -f $proj/s3.fit.summary ]] || { echo "no placed socket 3 build in $proj (rtl/s3/build.sh $proj)" >&2; exit 1; }
for f in "${X86_SRCS[@]}" s3/*.sv; do
    [[ $f -ot $proj/s3.map.rpt ]] || { echo "$f is newer than the build in $proj: build again" >&2; exit 1; }
done
for b in "${progs[@]}"; do
    [[ -f $bench/$b.hex && -f $bench/$b.mark ]] || { echo "$b: not in $bench (run x86_bench.sh first)" >&2; exit 1; }
done
mkdir -p "$out"
nice -n 19 verilator --cc --exe --build -j 4 -Wall -Wno-UNUSEDSIGNAL --trace --trace-structs --trace-max-array 4096 \
    --top-module core_top --Mdir "$out/obj" "${X86_SRCS[@]}" tests/x86/tb/core_top.sv tests/x86/tb/core_tb.cpp -o core_tb \
    > "$out/build.log" 2>&1 || { grep -m20 -A3 "%Error\|%Warning" "$out/build.log"; exit 1; }

qsf=$proj/s3.qsf
cp "$qsf" "$out/s3.qsf.orig"
trap 'cp "$out/s3.qsf.orig" "$qsf"' EXIT          # the build's own settings back, whatever happens
row="| $(date +%F) | $(git describe --always --dirty) | $(grep -m1 "^Device" $proj/s3.fit.summary | sed 's/.*: //') | ${note//|//} |"
for b in "${progs[@]}"; do
    res=$("$out/obj/core_tb" "+image=$bench/$b.hex" "+trace=$out/$b.trace" "+ticks=$CYCLES" "+mark=$(cat "$bench/$b.mark")" \
          +mem_lat=10 "+vcd=$out/$b.raw.vcd" "+vcd_cycles=$CYCLES" "+vcd_ns=$CORE_NS" 2>&1) || { echo "$b: $res" >&2; exit 1; }
    rm -f "$out/$b.trace"
    ipc=$(awk '{ print $NF }' <<< "${res##*$'\n'}")
    python3 -I tools/vcd_scope.py "$out/$b.raw.vcd" "$out/$b.vcd" TOP.core_top.core s3_top.core x86_core "${X86_SRCS[@]}"
    rm -f "$out/$b.raw.vcd"
    cp "$out/s3.qsf.orig" "$qsf"
    { echo
      echo "set_global_assignment -name POWER_USE_INPUT_FILES ON"
      echo "set_global_assignment -name POWER_INPUT_FILE_NAME \"$(realpath "$out/$b.vcd")\" -section_id run"
      echo "set_instance_assignment -name POWER_READ_INPUT_FILE run -to s3_top"
      echo "set_global_assignment -name POWER_VCD_FILE_START_TIME \"0 ps\" -section_id run"
      echo "set_global_assignment -name POWER_VCD_FILE_END_TIME \"$((CYCLES * CORE_NS * 1000)) ps\" -section_id run"; } >> "$qsf"
    (cd "$proj" && nice -n 19 "$QUARTUS/quartus_pow" s3 > "../x86/power/$b.pow.log" 2>&1) \
        || { echo "$b: quartus_pow failed, see $out/$b.pow.log" >&2; exit 1; }
    rm -f "$out/$b.vcd"
    w=$(awk -F': ' '/^Total Thermal Power Dissipation/ { sub(/ mW/, "", $2); printf "%.2f", $2 / 1000 }' $proj/s3.pow.summary)
    sim=$(grep -m1 "Number of signals with Toggle Rate from Simulation" $proj/s3.pow.rpt | awk -F';' '{ print $5 }' | tr -d ' ')
    nj=$(awk -v w="$w" -v ipc="$ipc" -v ns="$CORE_NS" 'BEGIN { printf "%.2f", w * ns / ipc }')
    echo "$b: IPC $ipc, $w W, $nj nJ / instruction (registers from the simulation: $sim)"
    row+=" $w / $nj |"
done
if [[ $(grep '^| date ' "$hist" | tail -n 1) != "| date | commit | device | change | $(printf '%s | ' "${progs[@]}")" ]]; then
    { echo; echo "| date | commit | device | change | $(printf '%s | ' "${progs[@]}")"
      echo "|$(printf -- '---|%.0s' $(seq $(( ${#progs[@]} + 4 ))))"; } >> "$hist"
fi
echo "$row" >> "$hist"
