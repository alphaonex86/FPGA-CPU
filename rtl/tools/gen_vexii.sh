#!/bin/bash
# Usage: rtl/tools/gen_vexii.sh <config>   (configs: vexii_configs.sh)
# Generates one configuration (fpgacpu.Generate: VexiiRiscv back end + this
# tree's front ends) into rtl/build/<config>/VexiiRiscv.v (plan/cpu_core.md).
set -eu
cd "$(dirname "$0")/.."
. tools/vexii_configs.sh
vexii_args "${1:-}"
[[ -x ext/sbt/bin/sbt ]] || { echo "run rtl/tools/setup.sh first"; exit 1; }
out=build/$1
mkdir -p "$out"
# rtl/src (fpgacpu.*, our front ends) compiles on top of the pinned VexiiRiscv
(cd ext/VexiiRiscv && nice -n 19 ../sbt/bin/sbt -batch \
    "set Compile / unmanagedSourceDirectories += file(\"$PWD/../../src\")" \
    "runMain fpgacpu.Generate $args") > "$out/gen.log" 2>&1 || {
    grep -m10 "\[error\]" "$out/gen.log"; echo "FAIL see rtl/$out/gen.log"; exit 1; }
mv ext/VexiiRiscv/VexiiRiscv.v "$out/"
echo "wrote rtl/$out/VexiiRiscv.v ($(wc -l < "$out/VexiiRiscv.v") lines)"
