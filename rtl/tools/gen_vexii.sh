#!/bin/bash
# Usage: rtl/tools/gen_vexii.sh <config>   (configs below)
# Generates the VexiiRiscv back end of one configuration into
# rtl/build/<config>/VexiiRiscv.v (plan/cpu_core.md next step 1).
set -eu
cd "$(dirname "$0")/.."
# dual-issue RV64, MMU (from --with-supervisor), 16 KB (64 sets x 4 ways)
# L1 I/D; sync register file and TLB: Cyclone V RAM reads are registered
BASE="--xlen=64 --with-mul --with-div --with-rva --with-rvc --with-supervisor
 --mmu-sync-read --dual-issue --max-ipc --regfile-sync --fetch-l1 --fetch-l1-sets=64
 --fetch-l1-ways=4 --lsu-l1 --lsu-l1-sets=64 --lsu-l1-ways=4"
case ${1:-} in
    rv64imac_dual) args=$BASE ;;
    rv64imafdc_dual) args="$BASE --with-rvd" ;;
    *) echo "usage: $0 rv64imac_dual|rv64imafdc_dual"; exit 1 ;;
esac
[[ -x ext/sbt/bin/sbt ]] || { echo "run rtl/tools/setup.sh first"; exit 1; }
out=build/$1
mkdir -p "$out"
(cd ext/VexiiRiscv && nice -n 19 ../sbt/bin/sbt -batch \
    "Test/runMain vexiiriscv.Generate $(echo $args)") > "$out/gen.log" 2>&1 || {
    grep -m10 "\[error\]" "$out/gen.log"; echo "FAIL see rtl/$out/gen.log"; exit 1; }
mv ext/VexiiRiscv/VexiiRiscv.v "$out/"
echo "wrote rtl/$out/VexiiRiscv.v ($(wc -l < "$out/VexiiRiscv.v") lines)"
