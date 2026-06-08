// C-Model DPI Wrapper: alu
// Generic: signal list from context, auto-generated
#include "svdpi.h"
#include "alu_ref_model.h"
#include <cstdio>

static alu_ref_model* g_model = nullptr;

extern "C" void alu_dpi_init() {
    if (!g_model) {
        g_model = new alu_ref_model();
        printf("[DPI] alu C-Model initialized\n");
    }
}

extern "C" void alu_dpi_predict(
    int a,
    int b,
    int op,
    int* result,
    int* flags,
    int* valid
) {
    if (!g_model) alu_dpi_init();
    g_model->predict(
        a,
        b,
        op,
        *result,
        *flags,
        *valid
    );
}

extern "C" void alu_dpi_shutdown() {
    if (g_model) { delete g_model; g_model = nullptr; }
}
