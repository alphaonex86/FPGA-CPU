#!/bin/bash
# Usage: rtl/tools/x86_test.sh <test.S | test.c> [trace.txt]
# Builds a flat 32-bit x86 test (loaded at 0x1000) into rtl/build/x86/<name>.bin
# (C: gcc i686 freestanding, -O2 or the flags of a "// cflags: ..." line,
# entered by tests/x86/lib/crt0.S at main);
# without a trace prints the Unicorn reference trace, with one checks it
# (rtl/tools/x86_trace_check.c, built by setup.sh).
set -eu
src=$(realpath "$1")
trace=${2:+$(realpath "$2")}
cd "$(dirname "$0")/.."
check=ext/x86_trace_check
[[ -x $check ]] || { echo "run rtl/tools/setup.sh first"; exit 1; }
name=$(basename "${src%.*}")
mkdir -p build/x86
objs=()
if [[ $src == *.c ]]; then
    as --32 -o build/x86/crt0.o tests/x86/lib/crt0.S
    cflags=$(sed -n 's|^// cflags: ||p' "$src")
    # shellcheck disable=SC2086
    gcc -m32 -march=i686 -mno-sse ${cflags:--O2} -ffreestanding -fno-pic -fno-stack-protector -fno-reorder-functions \
        -fno-asynchronous-unwind-tables -c -o "build/x86/$name.o" "$src"
    objs=(build/x86/crt0.o)
else
    as --32 -o "build/x86/$name.o" "$src"
fi
ld -m elf_i386 -Ttext=0x1000 --oformat binary -o "build/x86/$name.bin" "${objs[@]}" "build/x86/$name.o"
if [[ -n $trace ]]; then
    "$check" "build/x86/$name.bin" 1000 "$trace"
else
    "$check" --gen "build/x86/$name.bin" 1000 100000
fi
