#!/bin/bash
# Usage: rtl/tools/x86_synth.sh <out dir> [recipe]
# Compiles the x86 core (rtl/tests/x86/synth/x86_core_synth.sv harness) on
# 5CEFA9F23C8 with synth_cv.sh (recipe default | perf), then prints the
# worst path (synth_path.sh). Run from a copy of rtl/ to keep editing the
# tree while Quartus reads the sources.
set -eu
out=$(realpath -m "$1")
cd "$(dirname "$0")/.."
. tools/x86_files.sh
tools/synth_cv.sh tests/x86/synth/x86_core_synth.sv "$out" 10.0 "${2:-default}" "${X86_SRCS[@]}"
tools/synth_path.sh "$out"
