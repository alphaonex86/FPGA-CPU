#!/bin/bash
# Usage: rtl/tools/x86_test.sh <test.S> [trace.txt]
# Assembles a flat 32-bit x86 test (loaded at 0x1000) into rtl/build/x86/<name>.bin;
# without a trace prints the Unicorn reference trace, with one checks it
# (rtl/tools/x86_trace_check.c, built by setup.sh).
set -eu
src=$(realpath "$1")
trace=${2:+$(realpath "$2")}
cd "$(dirname "$0")/.."
check=ext/x86_trace_check
[[ -x $check ]] || { echo "run rtl/tools/setup.sh first"; exit 1; }
name=$(basename "$src" .S)
mkdir -p build/x86
as --32 -o "build/x86/$name.o" "$src"
ld -m elf_i386 -Ttext=0x1000 --oformat binary -o "build/x86/$name.bin" "build/x86/$name.o"
if [[ -n $trace ]]; then
    "$check" "build/x86/$name.bin" 1000 "$trace"
else
    "$check" --gen "build/x86/$name.bin" 1000 100000
fi
