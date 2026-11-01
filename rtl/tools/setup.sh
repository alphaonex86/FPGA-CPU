#!/bin/bash
# Fetch the VexiiRiscv back end (pinned) + SpinalHDL + sbt, and the Unicorn
# x86 lock-step reference (C3, testbench only, GPLv2), into rtl/ext/.
# Re-runnable: existing pieces are kept. plan/cpu_core.md next step 1.
set -eu
cd "$(dirname "$0")/.."
VEXII_COMMIT=9f70315deb3390b283995c5b8f1bd38215ecf52b
SBT_VERSION=1.10.0                         # VexiiRiscv project/build.properties
UNICORN_TAG=2.1.4
mkdir -p ext
if [[ ! -d ext/VexiiRiscv ]]; then
    git clone https://github.com/SpinalHDL/VexiiRiscv.git ext/VexiiRiscv
fi
git -C ext/VexiiRiscv checkout -q "$VEXII_COMMIT"
git -C ext/VexiiRiscv submodule update --init ext/SpinalHDL ext/rvls ext/NaxSoftware  # rvls: Scala bindings; NaxSoftware: bench ELFs
# our changes to the pinned VexiiRiscv, in order; already applied ones are skipped
for p in patches/vexii/*.patch; do
    if git -C ext/VexiiRiscv apply --check "$PWD/$p" 2>/dev/null; then
        git -C ext/VexiiRiscv apply "$PWD/$p"
    elif ! git -C ext/VexiiRiscv apply --check -R "$PWD/$p" 2>/dev/null; then
        echo "FAIL $p applies neither forward nor reversed on ext/VexiiRiscv"; exit 1
    fi
done
if [[ ! -x ext/sbt/bin/sbt ]]; then
    curl -sfL -o ext/sbt.tgz \
        "https://github.com/sbt/sbt/releases/download/v$SBT_VERSION/sbt-$SBT_VERSION.tgz"
    tar -xzf ext/sbt.tgz -C ext
    rm ext/sbt.tgz
fi
ext/sbt/bin/sbt --version
if [[ ! -f ext/unicorn/build/libunicorn.a ]]; then
    [[ -d ext/unicorn ]] || git clone -q --depth 1 -b "$UNICORN_TAG" \
        https://github.com/unicorn-engine/unicorn.git ext/unicorn
    cmake -S ext/unicorn -B ext/unicorn/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
        -DUNICORN_ARCH=x86 -DUNICORN_BUILD_TESTS=OFF -DBUILD_SHARED_LIBS=OFF
    nice -n 19 ninja -C ext/unicorn/build
fi
cc -O2 -Wall -Werror -Iext/unicorn/include -o ext/x86_trace_check tools/x86_trace_check.c \
    ext/unicorn/build/libunicorn.a -lpthread -lm
