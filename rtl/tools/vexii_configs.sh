# Sourced by gen_vexii.sh / bench_vexii.sh: vexii_args <config> sets $args
# (VexiiRiscv ParamSimple options) and $isa (NaxSoftware build folder).
# RV64, MMU (from --with-supervisor), 16 KB (64 sets x 4 ways) L1 I/D;
# sync register file and TLB: Cyclone V RAM reads are registered
BASE="--xlen=64 --with-mul --with-div --with-rva --with-rvc --with-supervisor
 --mmu-sync-read --regfile-sync --fetch-l1 --fetch-l1-sets=64 --fetch-l1-ways=4
 --lsu-l1 --lsu-l1-sets=64 --lsu-l1-ways=4"
# options are applied in order: the --without/--allow ones undo part of
# --max-ipc (late ALU, bypass from stage 0) for the fmax vs IPC sweep
DUAL="$BASE --dual-issue --max-ipc"
CONFIGS="rv64imac_dual rv64imafdc_dual rv64imac_dual_nolate
 rv64imac_dual_nolate_bp1 rv64imac_single rv64imac_dual_rbra"

vexii_args() {
    isa=rv64imac
    case ${1:-} in
        rv64imac_dual) args=$DUAL ;;
        rv64imafdc_dual) args="$DUAL --with-rvd"; isa=rv64imafdc ;;
        rv64imac_dual_nolate) args="$DUAL --without-late-alu" ;;
        rv64imac_dual_nolate_bp1) args="$DUAL --without-late-alu --allow-bypass-from=1" ;;
        rv64imac_single) args="$BASE --max-ipc" ;;
        # early-ALU branch redirects one cycle later (execute -> fetch path)
        rv64imac_dual_rbra) args="$DUAL --relaxed-branch" ;;
        *) echo "unknown config '${1:-}', one of:" $CONFIGS; return 1 ;;
    esac
    args=$(echo $args)
}
