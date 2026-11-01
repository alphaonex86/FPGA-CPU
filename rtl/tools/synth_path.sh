#!/bin/bash
# Usage: rtl/tools/synth_path.sh <synth_cv.sh out dir>
# Worst setup path of a finished synth_cv.sh run (slow model): end points,
# arrival time, then the cells along it grouped by RTL node name, in order.
set -eu
cd "$1"
[[ -f core.sta.rpt ]] || { echo "no core.sta.rpt in $PWD: run synth_cv.sh first"; exit 1; }
sta=$(dirname "$(command -v quartus_sh || ls ~/altera_lite/*/quartus/bin/quartus_sh | head -1)")/quartus_sta
cat > path.tcl <<'TCL'
project_open core
create_timing_netlist -model slow
read_sdc
update_timing_netlist
report_timing -setup -npaths 1 -detail full_path -file path.txt
TCL
nice -n 19 "$sta" -t path.tcl > path.log 2>&1 || { echo "FAIL see $PWD/path.log"; exit 1; }
grep -E "^; (From Node|To Node|Data Arrival Time)" path.txt
awk '/Data Arrival Path/,/Data Required Path/' path.txt | grep CELL \
    | awk -F';' '{ n = $8; gsub(/ /, "", n); sub(/\|[a-z]+$/, "", n); print n }' \
    | sed -E 's/^[^|]*\|//; s/~[0-9A-Z_]*//g; s/\[[0-9]+\]//g' \
    | awk '{ if ($0 != last) { if (n) print n, last; last = $0; n = 0 } n++ } END { print n, last }'
