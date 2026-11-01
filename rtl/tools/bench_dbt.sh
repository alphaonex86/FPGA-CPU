#!/bin/bash
# Usage (on the DE25-Nano HPS, Ubuntu 22.04 arm64 SD image, as a sudo user,
# with network): bench_dbt.sh [workdir]
# D30 / plan/slot1_variants.md variant B: how far x86 under dynamic binary
# translation is from native on one Cortex-A76. CoreMark built natively
# (aarch64) and for x86-64 / i686, run pinned to one A76:
#   native | FEX x86-64 / i686, TSO on and off | Box64 x86-64 (no TSO
#   emulation by default). Prints iterations/s and % of native.
# FEX runs static guests (no x86 rootfs needed); Box64 runs a dynamic one
# (it maps libc to the native one).
set -eu
work=$(realpath -m "${1:-$HOME/bench_dbt}")
coremark_commit=1f483d5
mkdir -p "$work"
cd "$work"
log=$work/bench.log
: > "$log"

[[ $(uname -m) == aarch64 ]] || { echo "run this on the DE25 HPS (aarch64), not $(uname -m)"; exit 1; }
# Cortex-A76 = CPU part 0xd0b (Arm A76 TRM, MIDR)
a76=$(awk '/^processor/ {p = $3} /^CPU part/ && $4 == "0xd0b" {print p; exit}' /proc/cpuinfo)
[[ -n $a76 ]] || { echo "no Cortex-A76 (CPU part 0xd0b) in /proc/cpuinfo"; exit 1; }
echo "pinned to cpu $a76 (Cortex-A76)" | tee -a "$log"

sudo apt-get update
sudo apt-get install -y git build-essential cmake ninja-build python3 \
    software-properties-common gcc-x86-64-linux-gnu libc6-dev-amd64-cross \
    gcc-i686-linux-gnu libc6-dev-i386-cross
if ! command -v FEXInterpreter > /dev/null && ! command -v FEX > /dev/null; then
    sudo add-apt-repository -y ppa:fex-emu/fex
    sudo apt-get update
    sudo apt-get install -y fex-emu-armv8.2   # A76 is Armv8.2-A
fi
fex=$(command -v FEX || command -v FEXInterpreter) || { echo "FEX not installed"; exit 1; }

[[ -d box64 ]] || git clone --depth 1 https://github.com/ptitSeb/box64.git
if [[ ! -x box64/build/box64 ]]; then
    cmake -S box64 -B box64/build -G Ninja -DARM_DYNAREC=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo
    ninja -C box64/build
fi
box64=$work/box64/build/box64
echo "box64 $(git -C box64 rev-parse --short HEAD), $("$fex" --version 2>&1 | head -1)" | tee -a "$log"

if [[ ! -d coremark ]]; then
    git clone https://github.com/eembc/coremark.git
    git -C coremark checkout -q $coremark_commit
fi
build() {   # <out> <cc> [extra flags]
    make -s -C coremark clean > /dev/null
    make -s -C coremark compile PORT_DIR=linux CC="$2" XCFLAGS="${3:-}" OUTFILE="$work/$1" \
        || { echo "FAIL building $1"; exit 1; }
}
build cm_native gcc
build cm_x64_static x86_64-linux-gnu-gcc -static
build cm_x64_dyn x86_64-linux-gnu-gcc
build cm_i686_static i686-linux-gnu-gcc -static

run() {   # <label> <command...>: CoreMark iterations/s
    local out
    out=$(taskset -c "$a76" "${@:2}" 2>&1) || { echo "$out" >> "$log"; echo "FAIL $1" | tee -a "$log"; return 1; }
    echo "$out" >> "$log"
    grep -q "Correct operation validated" <<< "$out" || { echo "FAIL $1: result not validated" | tee -a "$log"; return 1; }
    awk -F: '/Iterations\/Sec/ {gsub(/ /, "", $2); print $2}' <<< "$out"
}
rc=0
native=$(run native ./cm_native) || exit 1
printf "%-24s %12s %8s\n" case "iter/s" "native" | tee -a "$log"
printf "%-24s %12.1f %7.1f%%\n" native "$native" 100 | tee -a "$log"
report() {   # <label> <command...>
    local v
    v=$(run "$@") || { rc=1; return; }
    printf "%-24s %12.1f %7.1f%%\n" "$1" "$v" "$(awk -v v="$v" -v n="$native" 'BEGIN {print v * 100 / n}')" | tee -a "$log"
}
report "FEX x86-64 TSO on" "$fex" ./cm_x64_static
report "FEX x86-64 TSO off" env FEX_TSOENABLED=0 "$fex" ./cm_x64_static
report "FEX i686 TSO on" "$fex" ./cm_i686_static
report "FEX i686 TSO off" env FEX_TSOENABLED=0 "$fex" ./cm_i686_static
report "Box64 x86-64" "$box64" ./cm_x64_dyn
echo "full output: $log"
exit $rc
