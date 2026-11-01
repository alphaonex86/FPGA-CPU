# Sourced by synth_cv.sh / synth_z486.sh. DEVICE picks the chip and its
# Quartus: 5CE* Cyclone V (Lite), A5E* Agilex 5 (Pro, DE25-Nano). Run in a
# directory holding core.qsf: quartus_compile <recipe> appends the recipe
# (default | perf), compiles, checks clk is the only real pin and that no
# latch was inferred, and prints ALMs, registers, RAM, DSP and the worst
# slow-model fmax.
DEVICE=${DEVICE:-5CEFA9F23C8}
case $DEVICE in
    5CE*) FAMILY="Cyclone V"; QUARTUS=${QUARTUS:-$HOME/altera_lite/25.1std/quartus/bin} ;;
    A5E*) FAMILY="Agilex 5"; QUARTUS=${QUARTUS:-$HOME/altera_pro/26.1.1/quartus/bin} ;;
    *) echo "unknown DEVICE '$DEVICE' (5CE* | A5E*)"; exit 1 ;;
esac
TOOLS=$(realpath "$(dirname "${BASH_SOURCE[0]}")")

quartus_compile() {
    case $1 in
        default) ;;
        perf) [[ $FAMILY == "Cyclone V" ]] || { echo "perf recipe is Cyclone V only"; return 1; }
              cat "$TOOLS/quartus_perf.qsf" >> core.qsf ;;
        *) echo "unknown recipe '$1' (default | perf)"; return 1 ;;
    esac
    echo "PROJECT_REVISION = \"core\"" > core.qpf
    nice -n 19 "$QUARTUS/quartus_sh" --flow compile core > flow.log 2>&1 || {
        grep -m5 "^Error" flow.log || true; echo "FAIL see $PWD/flow.log"; return 1; }
    if grep -q "fed by virtual pin" flow.log || ! grep -q "^Total pins : 1 /" core.fit.summary; then
        echo "FAIL clk is not the only real pin"; return 1; fi
    # Lite 10240 "inferring latch(es)", Pro 19651 "latch inferred"
    if grep -E "inferring latch|latch inferred" flow.log; then echo "FAIL latch in the RTL"; return 1; fi
    grep -E "Logic utilization|Total (dedicated logic )?registers|Total block memory bits|Total RAM Blocks|Total DSP Blocks" \
        core.fit.summary
    # Cyclone V multicorner: per-corner tables, the first is slow 1100 mV 85 C;
    # multicorner off (perf) and Agilex 5: one "Fmax Summary", worst corner.
    grep -A6 -E "^; (Slow 1100mV 85C Model )?Fmax Summary" core.sta.rpt | grep -m1 MHz \
        || { echo "FAIL no fmax in $PWD/core.sta.rpt"; return 1; }
}
