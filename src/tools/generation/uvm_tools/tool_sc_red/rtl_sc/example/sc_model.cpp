// SC single-channel model: config received via own target_socket, parsed internally.

#include <systemc.h>
#include <tlm.h>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>
#include <cstring>
#include <cstdint>

#include "sc_registry.h"

static uint64_t bswap64(uint64_t v) {
    uint64_t r = 0;
    for (int i = 0; i < 8; i++) r |= ((v >> (i*8)) & 0xFF) << ((7-i)*8);
    return r;
}
static uint32_t bswap32(uint32_t v) {
    return ((v>>24)&0xFF)|((v>>8)&0xFF00)|((v<<8)&0xFF0000)|((v<<24)&0xFF000000u);
}

#pragma pack(push, 1)
struct simple_cfg_t {
    uint64_t base_addr;
    uint32_t beat_size;
    uint32_t num_beats;
};
#pragma pack(pop)

SC_MODULE(sc_model) {
    sc_in<bool> clk;

    tlm_utils::simple_initiator_socket<sc_model> data_socket;
    tlm_utils::simple_target_socket<sc_model> cfg_socket;

    simple_cfg_t cfg;
    sc_event cfg_event;

    SC_CTOR(sc_model) : data_socket("data_socket"), cfg_socket("cfg_socket") {
        cfg_socket.register_b_transport(this, &sc_model::cfg_b_transport);
        SC_THREAD(run);
        sensitive << clk.pos();
    }

    // Receive config struct, parse internally
    void cfg_b_transport(tlm::tlm_generic_payload& gp, sc_time& delay) {
        unsigned char* ptr = gp.get_data_ptr();
        unsigned int len = gp.get_data_length();
        if (len >= sizeof(simple_cfg_t))
            memcpy(&cfg, ptr, sizeof(simple_cfg_t));
        gp.set_response_status(tlm::TLM_OK_RESPONSE);
        cfg_event.notify();
    }

    void send(uint64_t addr, const unsigned char* buf, unsigned int len, unsigned int seq) {
        tlm::tlm_generic_payload gp;
        sc_time delay = SC_ZERO_TIME;
        unsigned char local[64];
        unsigned int n = (len > 64) ? 64 : len;
        memset(local, 0, 64);
        memcpy(local, buf, n);

        gp.set_command(tlm::TLM_WRITE_COMMAND);
        gp.set_address(addr);
        gp.set_data_ptr(local);
        gp.set_data_length(n);
        gp.set_streaming_width(seq);
        gp.set_byte_enable_ptr(nullptr);
        gp.set_byte_enable_length(0);
        gp.set_response_status(tlm::TLM_INCOMPLETE_RESPONSE);
        data_socket->b_transport(gp, delay);
    }

    void run() {
        // Wait for config struct to arrive
        wait(cfg_event);

        uint64_t base  = bswap64(cfg.base_addr);
        uint32_t bsize = bswap32(cfg.beat_size);
        uint32_t beats = bswap32(cfg.num_beats);

        for (unsigned int i = 0; i < beats; i++) {
            unsigned char data[64];
            for (unsigned int b = 0; b < bsize && b < 64; b++)
                data[b] = (i * bsize + b) & 0xFF;
            send(base + i * bsize, data, bsize, i);
            wait();
        }
    }
};

int sc_main(int argc, char* argv[]) {
    sc_clock clk("clk", 10, SC_NS);

    sc_model model("model");
    model.clk(clk);

    // One-line registrations
    sc_registry::reg("data0", model.data_socket);
    sc_registry::reg_cfg("cfg0", model.cfg_socket);
    sc_registry::connect_all();

    sc_start(-1);
    return 0;
}
