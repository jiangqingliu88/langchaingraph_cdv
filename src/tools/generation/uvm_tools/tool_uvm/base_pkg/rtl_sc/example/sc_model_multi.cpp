// Multi-channel SC model: 4 channels with different data widths.

#include <systemc.h>
#include <tlm.h>
#include <tlm_utils/simple_initiator_socket.h>
#include <cstring>

#include "sc_registry.h"

SC_MODULE(sc_multi_model) {
    sc_in<bool> clk;

    tlm_utils::simple_initiator_socket<sc_multi_model, 32, tlm::tlm_base_protocol_types, 0> sock_64;
    tlm_utils::simple_initiator_socket<sc_multi_model, 32, tlm::tlm_base_protocol_types, 1> sock_128;
    tlm_utils::simple_initiator_socket<sc_multi_model, 32, tlm::tlm_base_protocol_types, 2> sock_256;
    tlm_utils::simple_initiator_socket<sc_multi_model, 32, tlm::tlm_base_protocol_types, 3> sock_512;

    SC_CTOR(sc_multi_model)
        : sock_64("sock_64"), sock_128("sock_128"),
          sock_256("sock_256"), sock_512("sock_512")
    {
        SC_THREAD(run_64);  sensitive << clk.pos();
        SC_THREAD(run_128); sensitive << clk.pos();
        SC_THREAD(run_256); sensitive << clk.pos();
        SC_THREAD(run_512); sensitive << clk.pos();
    }

    void send_data(tlm::tlm_initiator_socket<>& sock, uint64_t addr,
                   const unsigned char* buf, unsigned int len, unsigned int seq) {
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

        sock->b_transport(gp, delay);
    }

    void run_64() {
        for (int i = 0; i < 10; i++) wait();
        sc_cfg_receiver* cfg = sc_registry::get_cfg();
        uint64_t base = cfg ? cfg->read_reg(0x0000) : 0x2000;
        if (base == 0) base = 0x2000;

        for (int i = 0; i < 10; i++) {
            unsigned char data[8];
            for (int b = 0; b < 8; b++) data[b] = (i * 8 + b) & 0xFF;
            send_data(sock_64, base + i * 8, data, 8, i);
            wait();
        }
    }

    void run_128() {
        for (int i = 0; i < 10; i++) wait();
        sc_cfg_receiver* cfg = sc_registry::get_cfg();
        uint64_t base = cfg ? cfg->read_reg(0x0008) : 0x3000;
        if (base == 0) base = 0x3000;

        for (int i = 0; i < 10; i++) {
            unsigned char data[16];
            for (int b = 0; b < 16; b++) data[b] = (i * 16 + b) & 0xFF;
            send_data(sock_128, base + i * 16, data, 16, i);
            wait();
        }
    }

    void run_256() {
        for (int i = 0; i < 10; i++) wait();
        sc_cfg_receiver* cfg = sc_registry::get_cfg();
        uint64_t base = cfg ? cfg->read_reg(0x0010) : 0x4000;
        if (base == 0) base = 0x4000;

        for (int i = 0; i < 10; i++) {
            unsigned char data[32];
            for (int b = 0; b < 32; b++) data[b] = (i * 32 + b) & 0xFF;
            send_data(sock_256, base + i * 32, data, 32, i);
            wait();
        }
    }

    void run_512() {
        for (int i = 0; i < 10; i++) wait();
        sc_cfg_receiver* cfg = sc_registry::get_cfg();
        uint64_t base = cfg ? cfg->read_reg(0x0018) : 0x5000;
        if (base == 0) base = 0x5000;

        for (int i = 0; i < 10; i++) {
            unsigned char data[64];
            for (int b = 0; b < 64; b++) data[b] = (i * 64 + b) & 0xFF;
            send_data(sock_512, base + i * 64, data, 64, i);
            wait();
        }
    }
};

int sc_main(int argc, char* argv[]) {
    sc_clock clk("clk", 10, SC_NS);

    sc_multi_model model("model");
    model.clk(clk);

    // One-line registrations
    sc_registry::reg("pcie_64",  model.sock_64);
    sc_registry::reg("dma_128",  model.sock_128);
    sc_registry::reg("noc_256",  model.sock_256);
    sc_registry::reg("hbm_512",  model.sock_512);
    sc_registry::reg_cfg();
    sc_registry::connect_all();

    sc_start(-1);
    return 0;
}
