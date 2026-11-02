#!/bin/bash
# Usage: sw/c2-vmm/test.sh
# Builds c2-vmm and runs the test ROM on the sim backend (needs /dev/kvm).
set -eu
cd "$(dirname "$0")"
out=build
mkdir -p "$out"
gcc -O2 -Wall -Wextra -Werror -o "$out/c2-vmm" vmm.c shadow.c bus_sim.c bus_fpga.c
as --32 -o "$out/test_rom.o" test_rom.S
objcopy -O binary -j .text "$out/test_rom.o" "$out/test_rom.bin"
if timeout 60 "$out/c2-vmm" sim "$out/test_rom.bin"; then
    echo "PASS"
else
    echo "FAIL: exit code $? (the failed test ROM step, or a VMM error)"
    exit 1
fi
