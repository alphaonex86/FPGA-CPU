// cflags: -O2 -Iext/coremark -Itests/x86/coremark -Itests/x86 -DITERATIONS=1 -fno-tree-loop-distribute-patterns
// CoreMark 1.0 (rtl/ext/coremark, setup.sh), one iteration of the 2K
// performance run, as one translation unit; tests/x86/coremark/ is the port.
#include "core_list_join.c"
#include "core_main.c"
#include "core_matrix.c"
#include "core_state.c"
#include "core_util.c"
#include "coremark/core_portme.c"
