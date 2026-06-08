// Auto-generated test driver for alu_ref_model
// Compile: g++ -std=c++17 alu_ref_model.cpp test_alu_ref_model.cpp -o test_alu
// Run:     ./test_alu
#include "alu_ref_model.h"
#include <cstdio>

using namespace refmodel;

int main() {
    bool all_pass = true;
    alu_ref_model model;

    printf("=== alu Reference Model Self-Test ===\n\n");

    // ── reset check ──
    model.reset();
    printf("  reset : reg[0]=0x%08X (expect 0)\n", model.reg_read(0));

    printf("\n── Test Vectors ──\n");
    // [0] reset_check
    {
        input_txn in  = {0, 0, 0};
        output_txn out = model.predict(in);
        bool pass = (out.result == 0) && (out.flags == 1);
        printf("  [%d] %-20s: %s (got result=0x%08X flags=0x%02X)\n",
               0, "reset_check", pass ? "PASS" : "FAIL", out.result, out.flags);
        if (!pass) all_pass = false;
    }
    // [1] simple_add
    {
        input_txn in  = {1, 3, 5};
        output_txn out = model.predict(in);
        bool pass = (out.result == 8) && (out.flags == 0);
        printf("  [%d] %-20s: %s (got result=0x%08X flags=0x%02X)\n",
               1, "simple_add", pass ? "PASS" : "FAIL", out.result, out.flags);
        if (!pass) all_pass = false;
    }
    // [2] zero_result
    {
        input_txn in  = {1, 0, 0};
        output_txn out = model.predict(in);
        bool pass = (out.result == 0) && (out.flags == 1);
        printf("  [%d] %-20s: %s (got result=0x%08X flags=0x%02X)\n",
               2, "zero_result", pass ? "PASS" : "FAIL", out.result, out.flags);
        if (!pass) all_pass = false;
    }
    // [3] max_operands
    {
        input_txn in  = {1, 4294967295, 1};
        output_txn out = model.predict(in);
        bool pass = (out.result == 0) && (out.flags == 3);
        printf("  [%d] %-20s: %s (got result=0x%08X flags=0x%02X)\n",
               3, "max_operands", pass ? "PASS" : "FAIL", out.result, out.flags);
        if (!pass) all_pass = false;
    }
    // [4] reg_write_read
    {
        input_txn in  = {16, 57005, 0};
        output_txn out = model.predict(in);
        bool pass = (out.result == 57005) && (out.flags == 0);
        printf("  [%d] %-20s: %s (got result=0x%08X flags=0x%02X)\n",
               4, "reg_write_read", pass ? "PASS" : "FAIL", out.result, out.flags);
        if (!pass) all_pass = false;
    }

    printf("\n=== Result: %s ===\n", all_pass ? "ALL PASSED" : "SOME FAILED");
    return all_pass ? 0 : 1;
}