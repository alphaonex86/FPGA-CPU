#!/bin/bash
# Usage: sw/c2-vmm/test_rtl.sh
# Runs the test ROM through the bridge RTL (rtl/c2: PCIe TLP engine, card,
# link, cartridge; Verilator) on the c2-vmm "rtl" backend (needs /dev/kvm),
# three times: the cartridge's bus cycles served by the bus_sim devices
# (C++), by c2_loop_target (the bring-up bitstream's RTL devices), and as P6
# bus transactions (c2_p6_agent) answered by FPGAcommon's p6_bif chipset
# front end, whose host port the bus_sim devices serve.
# rtl/tests/c2/p6_bif.v: copy of FPGAcommon/rtl/cpu_p6/p6_bif.v at cdd16c2
# (the FPGAmotherboard chipset front end, same operator); refresh by copying.
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
as --32 -o "$out/test_rom.o" test_rom.S
objcopy -O binary -j .text "$out/test_rom.o" "$out/test_rom.bin"
python3 -I -c "import sys, struct; d = open(sys.argv[1], 'rb').read(); open(sys.argv[2], 'w').write(''.join('%08x\n' % w for w in struct.unpack('<%dI' % (len(d) // 4), d)))" \
    "$out/test_rom.bin" "$out/test_rom.hex"

# build <name> [defines...]
build() {
    local name=$1 flags=()
    shift
    for d; do flags+=(+define+"$d"); done
    # the C objects are link flags, not make dependencies: force the relink
    rm -f "$out/$name/c2-vmm-rtl"
    nice -n 19 verilator --cc --exe --build -j 0 -Wall -Wno-UNUSEDSIGNAL -Wno-PINCONNECTEMPTY --top-module c2_sim_top --Mdir "$out/$name" \
        "${flags[@]}" -GROM_HEX="\"$out/test_rom.hex\"" \
        -CFLAGS "-O2 -I$here ${*/#/-D}" -LDFLAGS "${objs[*]}" -o c2-vmm-rtl \
        "$rtl"/c2/c2_afifo.sv "$rtl"/c2/c2_req_sync.sv "$rtl"/c2/xilinx/c2_tlp.sv "$rtl"/c2/c2_card.sv \
        "$rtl"/c2/c2_cart.sv "$rtl"/c2/c2_loop_target.sv "$rtl"/c2/c2_p6_agent.sv "$rtl"/tests/c2/p6_bif.v \
        "$rtl"/tests/c2/c2_sim_top.sv "$rtl"/tests/c2/bus_rtl.cpp \
        > "$out/$name.log" 2>&1 || { grep -m20 -A3 "%Error\|%Warning\|error:" "$out/$name.log"; exit 1; }
}
build devices
build target C2_LOOP_TARGET
build p6 C2_P6

rc=0
for name in devices target p6; do
    echo "== $name"
    if timeout 600 "$out/$name/c2-vmm-rtl" -e 0xf4 rtl "$out/test_rom.bin"; then
        echo "PASS"
    else
        echo "FAIL: exit code $? (the failed test ROM step, or a VMM / bridge error)"
        rc=1
    fi
done
exit $rc
