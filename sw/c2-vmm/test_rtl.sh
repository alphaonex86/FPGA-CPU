#!/bin/bash
# Usage: sw/c2-vmm/test_rtl.sh
# Runs the test ROM through the bridge RTL (rtl/c2: card + link + cartridge,
# Verilator) instead of the sim backend: c2-vmm "rtl" backend (needs /dev/kvm).
set -eu
cd "$(dirname "$0")"
here=$(pwd)
rtl=$(realpath ../../rtl)
out=$here/build/rtl
mkdir -p "$out"
objs=()
for c in vmm.c shadow.c bus_sim.c bus_fpga.c; do
    gcc -O2 -Wall -Wextra -Werror -DC2_RTL -c -o "$out/${c%.c}.o" "$c"
    objs+=("$out/${c%.c}.o")
done
# the C objects are link flags, not make dependencies: force the relink
rm -f "$out/obj/c2-vmm-rtl"
nice -n 19 verilator --cc --exe --build -j 0 -Wall -Wno-UNUSEDSIGNAL --top-module c2_sim_top --Mdir "$out/obj" \
    -CFLAGS "-O2 -I$here" -LDFLAGS "${objs[*]}" -o c2-vmm-rtl \
    "$rtl"/c2/c2_afifo.sv "$rtl"/c2/c2_req_sync.sv "$rtl"/c2/xilinx/c2_tlp.sv "$rtl"/c2/c2_card.sv "$rtl"/c2/c2_cart.sv \
    "$rtl"/tests/c2/c2_sim_top.sv "$rtl"/tests/c2/bus_rtl.cpp \
    > "$out/build.log" 2>&1 || { grep -m20 -A3 "%Error\|%Warning\|error:" "$out/build.log"; exit 1; }
as --32 -o "$out/test_rom.o" test_rom.S
objcopy -O binary -j .text "$out/test_rom.o" "$out/test_rom.bin"
if timeout 600 "$out/obj/c2-vmm-rtl" rtl "$out/test_rom.bin"; then
    echo "PASS"
else
    echo "FAIL: exit code $? (the failed test ROM step, or a VMM / bridge error)"
    exit 1
fi
