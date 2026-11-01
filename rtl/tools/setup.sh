#!/bin/bash
# Fetch the VexiiRiscv back end (pinned) + SpinalHDL + sbt into rtl/ext/.
# Re-runnable: existing pieces are kept. plan/cpu_core.md next step 1.
set -eu
cd "$(dirname "$0")/.."
VEXII_COMMIT=9f70315deb3390b283995c5b8f1bd38215ecf52b
SBT_VERSION=1.10.0                         # VexiiRiscv project/build.properties
mkdir -p ext
if [[ ! -d ext/VexiiRiscv ]]; then
    git clone https://github.com/SpinalHDL/VexiiRiscv.git ext/VexiiRiscv
fi
git -C ext/VexiiRiscv checkout -q "$VEXII_COMMIT"
git -C ext/VexiiRiscv submodule update --init ext/SpinalHDL ext/rvls ext/NaxSoftware  # rvls: Scala bindings; NaxSoftware: bench ELFs
if [[ ! -x ext/sbt/bin/sbt ]]; then
    curl -sfL -o ext/sbt.tgz \
        "https://github.com/sbt/sbt/releases/download/v$SBT_VERSION/sbt-$SBT_VERSION.tgz"
    tar -xzf ext/sbt.tgz -C ext
    rm ext/sbt.tgz
fi
ext/sbt/bin/sbt --version
