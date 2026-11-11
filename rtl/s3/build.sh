#!/bin/bash
# Usage: rtl/s3/build.sh <out_dir>
# Compiles the socket3-cyclonev bitstream (s3_top.sv, 5CEFA9F23C8) with Quartus Lite on the board's
# own pin assignment (board.py qsf), the perf recipe (the core does not route without it); fails on a
# critical warning, an unplaced, ignored or incomplete pin assignment, an inferred latch, a timing
# violation, or a ball the board wires to something else than the fitter's pin report says
# (rtl/tools/fpga_pins.py).
set -eu
[[ $# -eq 1 ]] || { echo "usage: $0 <out_dir>"; exit 1; }
here=$(realpath "$(dirname "$0")")
QUARTUS=${QUARTUS:-$HOME/altera_lite/25.1std/quartus/bin}
mkdir -p "$1"
cd "$1"
rm -f s3.ok
python3 "$here/board.py" qsf s3.qsf
cat "$here/../tools/quartus_perf.qsf" >> s3.qsf
echo 'PROJECT_REVISION = "s3"' > s3.qpf
nice -n 19 "$QUARTUS/quartus_sh" --flow compile s3 > flow.log 2>&1 || {
    grep -m10 "^Error" flow.log || true; echo "FAIL see $PWD/flow.log"; exit 1; }
# 15706: an assignment to a missing node; 169085 / 176015: an unplaced pin; 15714: an incomplete I/O assignment
if grep -E "Critical Warning|Warning \((15706|169085|176015|15714)\)|inferring latch" flow.log s3.fit.rpt; then
    echo "FAIL see $PWD/flow.log"; exit 1; fi
grep -E "Logic utilization|Total registers|Total pins|Total block memory bits" s3.fit.summary
if grep -q "Timing requirements not met" s3.sta.rpt flow.log; then
    grep -B2 -A12 "Setup Summary" s3.sta.rpt | head -30; echo "FAIL timing"; exit 1; fi
grep -A8 -E "Setup Summary|Hold Summary" s3.sta.rpt | grep "^; [a-z]" | head -8
# vectorless estimate (default toggle rates): the heatsink question of plan/interposers.md D5
nice -n 19 "$QUARTUS/quartus_pow" s3 >> flow.log 2>&1 || { echo "FAIL quartus_pow, see $PWD/flow.log"; exit 1; }
grep -E "Total Thermal Power|Core Dynamic|Core Static|I/O Thermal" s3.pow.summary
python3 "$here/../tools/fpga_pins.py" socket3 s3.pin 2>&1 | grep -v "Debug: Adding"
touch s3.ok                      # a complete build: hw/tools/check_board.py asks for it
echo "socket 3: $PWD/s3.sof"
