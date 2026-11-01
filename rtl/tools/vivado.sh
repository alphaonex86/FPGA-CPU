#!/bin/bash
# Usage: rtl/tools/vivado.sh <script.tcl> [tclargs...]
# Runs Vivado ML Standard ($VIVADO, default the 2025.2 install of
# plan/slot1_variants.md C2) in batch mode on a Tcl script. Vivado needs the
# ncurses 5 ABI: without libncurses.so.5 on the system (Gentoo:
# sys-libs/ncurses-compat) it gets a shim of .so.6 links in rtl/build/.
set -eu
VIVADO=${VIVADO:-/mnt/data/perso/FPGA/AMD/Xilinx/2025.2/Vivado/bin/vivado}
[[ -x $VIVADO ]] || { echo "no Vivado at $VIVADO (set VIVADO)"; exit 1; }
[[ $# -ge 1 ]] || { echo "usage: $0 <script.tcl> [tclargs...]"; exit 1; }
script=$1
shift
if ! /sbin/ldconfig -p | grep -q "libncurses.so.5 "; then
    shim=$(realpath "$(dirname "$0")/..")/build/ncurses5
    mkdir -p "$shim"
    for l in libncurses libtinfo; do
        [[ -e /usr/lib64/$l.so.6 ]] || { echo "no /usr/lib64/$l.so.6 for the shim"; exit 1; }
        ln -sf "/usr/lib64/$l.so.6" "$shim/$l.so.5"
    done
    export LD_LIBRARY_PATH=$shim${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
fi
exec nice -n 19 "$VIVADO" -mode batch -nojournal -nolog -source "$script" ${1:+-tclargs "$@"}
