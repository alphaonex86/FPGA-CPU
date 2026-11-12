#!/bin/bash
# Usage: [X86_PARAMS="-GL1D_KB=32 ..."] [CONFIG="<name>"] rtl/tools/x86_bench.sh "<the change measured>"
# Run it in claude-route.slice (4 CPUs; it runs 4 simulations at a time).
# The benchmark set of the project's own core (rtl/x86; not the C2 Mu or any other external CPU). The
# same programs and sizes for every architecture (split or unified L1, sizes, caches resized at run
# time, anything else): rows compare architectures as well as changes. X86_PARAMS goes to Verilator
# (core_top parameters: L1I_KB, L1D_KB, L2_KB, or new ones), CONFIG names the configuration in the
# row (default: X86_PARAMS, or "default"). Programs are portable C: micro-benchmarks (one property
# each) and application profiles; the applications are built twice, generic (-march=i386: what any
# x86 runs) and with every instruction the core has (ISA_FULL). Each program loops forever (its main
# called again and again); its first run is the warm-up, then exactly TICKS cycles are measured
# (core_top +mark at the entry of its main) on the core model (+mem_lat=10); its score is the IPC of
# that window, the whole trace checked against Unicorn. A program the core cannot run yet (x87
# before M6) scores n/a. Every IPC goes to plan/bench_results.csv; plan/bench_history.md gets one
# row (the geometric mean of each group, then of all), under a new table when the set changed; each
# program is printed against the first run of the set with the same config.
set -euo pipefail
note=${1:?usage: [X86_PARAMS=...] [CONFIG=...] x86_bench.sh \"<the change measured>\"}
params=${X86_PARAMS:-}
config=${CONFIG:-${params:-default}}
TICKS=1000000
ISA_GEN="-march=i386"
ISA_FULL="-march=pentiumpro"    # the core's ISA: raise at M6 (x87 / MMX) and M7 (-march=pentium4 -mfpmath=sse)
M=tests/x86/bench/b_mem.c
C=tests/x86/bench/b_code.c
K=tests/x86/bench/m_core.c
A=tests/x86/bench
# name | group | source | cflags (empty: the source's "// cflags:" line, else -O2); group app: built twice
BENCH=(
    "lat_8k|lat|$M|-O2 -DLAT -DSIZE=8192"
    "lat_64k|lat|$M|-O2 -DLAT -DSIZE=65536"
    "lat_256k|lat|$M|-O2 -DLAT -DSIZE=262144"
    "lat_1m|lat|$M|-O2 -DLAT -DSIZE=1048576"
    "bw_8k|bw|$M|-O2 -DBW -DSIZE=8192"
    "bw_64k|bw|$M|-O2 -DBW -DSIZE=65536"
    "bw_256k|bw|$M|-O2 -DBW -DSIZE=262144"
    "bw_1m|bw|$M|-O2 -DBW -DSIZE=1048576"
    "copy_256k|bw|$M|-O2 -DCOPY -DSIZE=262144"
    "code_11k|code|$C|-O2 -DNFB=7"
    "code_87k|code|$C|-O2 -DNFB=10"
    "codedata_27k|code|$C|-O2 -DNFB=7 -DDL=3"
    "phase|phase|$A/b_phase.c|"
    "ilp|core|$K|-O2 -DILP"
    "chain|core|$K|-O2 -DCHAIN"
    "branch|core|$K|-O2 -DBRANCH"
    "call|core|$K|-O2 -DCALL"
    "coremark|app|tests/x86/c5_coremark.c|"
    "mix|app|tests/x86/c1_mix.c|"
    "core|app|tests/x86/c2_core.c|"
    "string|app|tests/x86/c3_string.c|"
    "bits|app|tests/x86/c4_bits.c|"
    "interp|app|$A/a_interp.c|"
    "objects|app|$A/a_objects.c|"
    "compress|app|$A/a_compress.c|"
    "sort|app|$A/a_sort.c|"
    "hash|app|$A/a_hash.c|"
    "crypto|app|$A/a_crypto.c|"
    "parse|app|$A/a_parse.c|"
    "fpu|fp|$A/b_fpu.c|"
)
cd "$(dirname "$0")/.."
out=build/x86/bench
hist=../plan/bench_history.md
csv=../plan/bench_results.csv
mkdir -p "$out"
. tools/x86_files.sh
# shellcheck disable=SC2086
nice -n 19 verilator --cc --exe --build -j 4 -Wall -Wno-UNUSEDSIGNAL --top-module core_top $params \
    --Mdir "$out/obj" "${X86_SRCS[@]}" tests/x86/tb/core_top.sv tests/x86/tb/core_tb.cpp -o core_tb > "$out/build.log" 2>&1 \
    || { grep -m20 -A3 "%Error\|%Warning" "$out/build.log"; exit 1; }

# build every program (one at a time: x86_test.sh shares crt0.o), find the entry of its main
progs=()        # name group
build() {       # name source cflags
    local b=$1
    { echo "// cflags: $3"
      echo "#define main bench_main"
      echo "#include \"../../../$2\""
      echo "#undef main"
      echo "// called through a volatile pointer: never inlined, its entry is the window's mark"
      echo "int main(void) { for (;;) { void (*volatile f)(void) = (void (*)(void))bench_main; f(); } }"; } > "$out/bench_$b.c"
    tools/x86_test.sh "$out/bench_$b.c" > /dev/null
    ld -m elf_i386 -Ttext=0x1000 -o "$out/$b.elf" build/x86/crt0.o "build/x86/bench_$b.o"
    nm "$out/$b.elf" | awk '$3 == "bench_main" { print $1 }' > "$out/$b.mark"
    [[ -s $out/$b.mark ]] || { echo "$b: no bench_main symbol" >&2; exit 1; }
    python3 -I -c "import sys; d = open(sys.argv[1], 'rb').read(); open(sys.argv[2], 'w').write(''.join('%02x\n' % b for b in d))" \
        "build/x86/bench_$b.bin" "$out/$b.hex"
}
for e in "${BENCH[@]}"; do
    IFS='|' read -r b group prog cflags <<< "$e"
    [[ -n $cflags ]] || cflags=$(sed -n 's|^// cflags: ||p' "$prog")
    cflags=${cflags:--O2}
    if [[ $group == app ]]; then
        build "$b-i386" "$prog" "$cflags $ISA_GEN"; progs+=("$b-i386 app_i386")
        build "$b-full" "$prog" "$cflags $ISA_FULL"; progs+=("$b-full app_full")
    elif [[ $group == fp ]]; then
        build "$b" "$prog" "$cflags $ISA_FULL"; progs+=("$b $group")
    else
        build "$b" "$prog" "$cflags $ISA_GEN"; progs+=("$b $group")
    fi
done

run_one() {     # -> $out/$1.res: the IPC, n/a, or FAIL <why>
    local b=$1 res
    if ! res=$("$out/obj/core_tb" "+image=$out/$b.hex" "+trace=$out/$b.trace" "+ticks=$TICKS" "+mark=$(cat "$out/$b.mark")" \
               +mem_lat=10 2>&1); then
        if [[ $res == *"FAIL unsupported instruction"* ]]; then echo "n/a"; else echo "FAIL $res"; fi
    elif ! ext/x86_trace_check --partial "build/x86/bench_$b.bin" 1000 "$out/$b.trace" > "$out/$b.check" 2>&1; then
        echo "FAIL trace (see $out/$b.check)"
    else
        awk '{ printf "%.3f\n", $NF }' <<< "${res##*$'\n'}"
    fi > "$out/$b.res"
    rm -f "$out/$b.trace"
}
for p in "${progs[@]}"; do
    run_one "${p%% *}" &
    while (( $(jobs -rp | wc -l) >= 4 )); do wait -n; done
done
wait

# the set: everything that changes the scores besides the core; a new table when it changes
set_id=$(printf '%s\n' "$TICKS" "$ISA_GEN" "$ISA_FULL" "${BENCH[@]}" | cat - "$M" "$C" "$K" $A/b_phase.c $A/a_*.c $A/b_fpu.c \
         tests/x86/c[1-5]_*.c tests/x86/tb/core_tb.cpp | sha1sum | cut -c1-8)
python3 -I - "$out" "$hist" "$csv" "$set_id" "$(date +%F)" "$(git describe --always --dirty)" "$config" "$note" \
    "$TICKS" "$ISA_GEN" "$ISA_FULL" "${progs[@]}" <<'EOF'
import csv, math, os, sys
out, hist, csv_path, set_id, date, commit, config, note, ticks, isa_gen, isa_full = sys.argv[1:12]
progs = [p.split() for p in sys.argv[12:]]
groups = ['lat', 'bw', 'code', 'phase', 'core', 'app_i386', 'app_full', 'fp']
res = {}
for name, _ in progs:
    r = open(os.path.join(out, name + '.res')).read().strip()
    if r.startswith('FAIL'):
        sys.exit('%s: %s' % (name, r))
    res[name] = r
def gmean(v):
    v = [float(x) for x in v if x != 'n/a']
    return '%.3f' % math.exp(sum(map(math.log, v)) / len(v)) if v else 'n/a'
cells = [gmean([res[n] for n, g in progs if g == grp]) for grp in groups] + [gmean(res.values())]
new = not os.path.exists(csv_path)
with open(csv_path, 'a', newline='') as f:
    w = csv.writer(f)
    if new:
        w.writerow(['set', 'date', 'commit', 'config', 'change', 'program', 'group', 'ipc'])
    for n, g in progs:
        w.writerow([set_id, date, commit, config, note, n, g, res[n]])
text = open(hist).read()
if 'Set %s:' % set_id not in text:
    with open(hist, 'a') as f:
        f.write('\nSet %s: %s cycles per program after its warm-up, +mem_lat=10, generic %s, full %s; %d programs.\n\n'
                % (set_id, ticks, isa_gen, isa_full, len(progs)))
        f.write('| date | commit | config | change | ' + ' | '.join(groups) + ' | all |\n')
        f.write('|' + '---|' * (len(groups) + 5) + '\n')
with open(hist, 'a') as f:
    f.write('| %s | %s | %s | %s | %s |\n' % (date, commit, config.replace('|', '/'), note.replace('|', '/'), ' | '.join(cells)))
for grp, c in zip(groups + ['all'], cells):
    print('%-9s %s' % (grp, c))
rows = [r for r in csv.DictReader(open(csv_path)) if r['set'] == set_id and r['config'] == config]
first = rows[0]
base = {r['program']: r['ipc'] for r in rows if (r['date'], r['commit'], r['change']) == (first['date'], first['commit'], first['change'])}
print('against the first run of set %s, config %s (%s, %s):' % (set_id, config, first['commit'], first['change']))
for n, g in progs:
    a, b = base.get(n, 'n/a'), res[n]
    print('  %-16s %-6s %s' % (n, b, '%+.1f %%' % (100 * (float(b) / float(a) - 1)) if 'n/a' not in (a, b) else ''))
EOF
