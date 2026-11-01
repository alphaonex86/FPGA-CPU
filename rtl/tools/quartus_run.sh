# Sourced by synth_cv.sh / synth_z486.sh. Run in a directory holding
# core.qsf: quartus_compile <recipe> appends the recipe (default | perf),
# compiles, checks clk stayed a real clock pin and prints ALMs, registers,
# RAM, DSP and the slow 85 C fmax.
QUARTUS=${QUARTUS:-$HOME/altera_lite/25.1std/quartus/bin}
TOOLS=$(realpath "$(dirname "${BASH_SOURCE[0]}")")

quartus_compile() {
    case $1 in
        default) ;;
        perf) cat "$TOOLS/quartus_perf.qsf" >> core.qsf ;;
        *) echo "unknown recipe '$1' (default | perf)"; return 1 ;;
    esac
    echo "PROJECT_REVISION = \"core\"" > core.qpf
    nice -n 19 "$QUARTUS/quartus_sh" --flow compile core > flow.log 2>&1 || {
        grep -m5 "^Error" flow.log || true; echo "FAIL see $PWD/flow.log"; return 1; }
    if grep -q "fed by virtual pin" flow.log; then echo "FAIL clk is a virtual pin"; return 1; fi
    grep -E "Logic utilization|Total registers|Total block memory bits|Total RAM Blocks|Total DSP Blocks" \
        core.fit.summary
    # Multicorner off (perf) reports one plain "Fmax Summary", still the slow 1100 mV 85 C model.
    grep -A6 -E "^; (Slow 1100mV 85C Model )?Fmax Summary" core.sta.rpt | grep -m1 MHz \
        || { echo "FAIL no fmax in $PWD/core.sta.rpt"; return 1; }
}
