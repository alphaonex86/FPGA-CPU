#!/bin/bash
# Usage: rtl/tools/x86_len_test.sh [bytes] [seed]
# M1 (plan/x86_core.md): random byte stream, decoded by GNU objdump as i386
# and i8086 code; x86_len_decode must give objdump's length at every start.
# Skipped: (bad), and [prefixes] FWAIT (9B) that objdump folds into the next x87
# instruction (for the CPU it is a 1-byte instruction).
# Then x86_predecode against x86_len_decode on [bytes] random 30-byte blocks.
set -eu
cd "$(dirname "$0")/.."
n=${1:-200000}
seed=${2:-1}
out=build/x86/len
mkdir -p "$out"
python3 -I -c "import random,sys; random.seed($seed); sys.stdout.buffer.write(bytes(random.getrandbits(8) for _ in range($n)))" > "$out/stream.bin"
nice -n 19 verilator --cc --exe --build -j 0 -Wall -Wno-UNUSEDSIGNAL --top-module x86_len_decode --Mdir "$out/obj" \
    x86/x86_opdecode.sv x86/x86_len_decode.sv tests/x86/tb/len_decode_tb.cpp -o len_decode_tb > "$out/build.log" 2>&1 ||
    { tail -20 "$out/build.log"; exit 1; }
rc=0
for m in "i386 1" "i8086 0"; do
    set -- $m
    objdump -D -b binary -m "$1" --insn-width=16 "$out/stream.bin" |
        awk -F'\t' '/^ *[0-9a-f]+:\t/ { a = $1; gsub(/[ :]/, "", a); off = strtonum("0x" a); n = split($2, b, " ");
                     for (i = 1; b[i] ~ /^(26|2e|36|3e|64|65|66|67|f0|f2|f3)$/; i++);
                     print off, n, ($3 ~ /\(bad\)/ || b[i] == "9b" && n > i) }' > "$out/ref_$1.txt"
    "$out/obj/len_decode_tb" "$out/stream.bin" "$out/ref_$1.txt" "$2" || rc=1
done
nice -n 19 verilator --cc --exe --build -j 0 -Wall -Wno-UNUSEDSIGNAL --top-module predecode_check \
    --Mdir "$out/pobj" x86/x86_opdecode.sv x86/x86_len_decode.sv x86/x86_predecode.sv \
    tests/x86/tb/predecode_check.sv tests/x86/tb/predecode_tb.cpp -o predecode_tb > "$out/pbuild.log" 2>&1 ||
    { tail -20 "$out/pbuild.log"; exit 1; }
"$out/pobj/predecode_tb" "$n" "$seed" || rc=1
exit $rc
