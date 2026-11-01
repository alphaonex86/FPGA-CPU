#!/bin/bash
# Usage: rtl/tools/bench_vexii.sh <config>   (configs: vexii_configs.sh)
# Runs the prebuilt NaxSoftware Dhrystone and CoreMark ELFs on one
# configuration in the VexiiRiscv Verilator testbench (no rvls lock-step
# check) and prints DMIPS/MHz, CoreMark/MHz and the committed IPC of each
# (testbench --print-stats): the IPC side of the
# fmax vs IPC sweep (plan/cpu_core.md).
set -eu
cd "$(dirname "$0")/.."
. tools/vexii_configs.sh
vexii_args "${1:-}"
[[ -x ext/sbt/bin/sbt ]] || { echo "run rtl/tools/setup.sh first"; exit 1; }
out=$PWD/build/$1
mkdir -p "$out"
nsf=ext/NaxSoftware/baremetal
for b in dhrystone_vexii coremark_vexii; do
    elf=$nsf/$b/build/$isa/$b.elf
    [[ -f ext/VexiiRiscv/$elf ]] || { echo "missing ext/VexiiRiscv/$elf"; exit 1; }
    (cd ext/VexiiRiscv && nice -n 19 ../sbt/bin/sbt -batch \
        "Test/runMain vexiiriscv.tester.TestBench $args --no-rvls-check --no-stdin --print-stats --load-elf $elf --fail-after 600000000") \
        > "$out/$b.log" 2>&1 || { tail -5 "$out/$b.log"; echo "FAIL see rtl/build/$1/$b.log"; exit 1; }
done
grep -h "DMIPS per Mhz" "$out/dhrystone_vexii.log" || { echo "FAIL no Dhrystone result"; exit 1; }
grep -h "Coremark/MHz" "$out/coremark_vexii.log" || { echo "FAIL no CoreMark result"; exit 1; }
grep -H "IPC  *:" "$out/dhrystone_vexii.log" "$out/coremark_vexii.log" | sed 's|^.*/\([a-z_]*\.log\):|\1:|'
