// SC side: each module has its own target_socket for config,
// parses the struct internally. No external cfg_receiver.

#include <systemc.h>
#include <tlm.h>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>
#include <cstring>
#include <cstdint>

#include "sc_registry.h"

// -------------------------------------------------------
// Byte swap (SV packed struct = big-endian)
// -------------------------------------------------------
static uint64_t bswap64(uint64_t v) {
    uint64_t r = 0;
    for (int i = 0; i < 8; i++) r |= ((v >> (i*8)) & 0xFF) << ((7-i)*8);
    return r;
}
static uint32_t bswap32(uint32_t v) {
    return ((v>>24)&0xFF) | ((v>>8)&0xFF00) | ((v<<8)&0xFF0000) | ((v<<24)&0xFF000000u);
}

// -------------------------------------------------------
// GP send helper
// -------------------------------------------------------
static void send_gp(tlm::tlm_initiator_socket<32>& sock,
                    uint64_t addr, const unsigned char* buf,
                    unsigned int len, unsigned int seq) {
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

// -------------------------------------------------------
// DMA model: 3 data sockets + 1 config target_socket
// -------------------------------------------------------
#pragma pack(push, 1)
struct dma_cfg_t {
    uint64_t base_addr_0;
    uint64_t base_addr_1;
    uint64_t base_addr_2;
    uint32_t burst_size;
    uint32_t num_beats;
};
#pragma pack(pop)

SC_MODULE(dma_model) {
    sc_in<bool> clk;

    tlm_utils::simple_initiator_socket<dma_model, 32, tlm::tlm_base_protocol_types, 0> sock_0;
    tlm_utils::simple_initiator_socket<dma_model, 32, tlm::tlm_base_protocol_types, 1> sock_1;
    tlm_utils::simple_initiator_socket<dma_model, 32, tlm::tlm_base_protocol_types, 2> sock_2;
    tlm_utils::simple_target_socket<dma_model> cfg_socket;

    dma_cfg_t cfg;
    sc_event cfg_event;

    SC_CTOR(dma_model)
        : sock_0("sock_0"), sock_1("sock_1"), sock_2("sock_2"),
          cfg_socket("cfg_socket")
    {
        cfg_socket.register_b_transport(this, &dma_model::cfg_b_transport);
        SC_THREAD(run_ch0); sensitive << clk.pos();
        SC_THREAD(run_ch1); sensitive << clk.pos();
        SC_THREAD(run_ch2); sensitive << clk.pos();
    }

    // Config: receive struct bytes, parse internally
    void cfg_b_transport(tlm::tlm_generic_payload& gp, sc_time& delay) {
        unsigned char* ptr = gp.get_data_ptr();
        unsigned int len = gp.get_data_length();
        if (len >= sizeof(dma_cfg_t))
            memcpy(&cfg, ptr, sizeof(dma_cfg_t));
        gp.set_response_status(tlm::TLM_OK_RESPONSE);
        cfg_event.notify();
    }

    void run_ch(tlm::tlm_initiator_socket<32>& sock, int ch_idx) {
        wait(cfg_event);

        uint64_t bases[3] = {bswap64(cfg.base_addr_0),
                             bswap64(cfg.base_addr_1),
                             bswap64(cfg.base_addr_2)};
        uint32_t burst = bswap32(cfg.burst_size);
        uint32_t beats = bswap32(cfg.num_beats);
        uint64_t base  = bases[ch_idx];

        for (unsigned int i = 0; i < beats; i++) {
            unsigned char data[32];
            for (unsigned int b = 0; b < burst && b < 32; b++)
                data[b] = (ch_idx * 64 + i * 32 + b) & 0xFF;
            send_gp(sock, base + i * burst, data, burst, i);
            wait(); wait(); wait();
        }
    }

    void run_ch0() { run_ch(sock_0, 0); }
    void run_ch1() { run_ch(sock_1, 1); }
    void run_ch2() { run_ch(sock_2, 2); }
};

// -------------------------------------------------------
// PCIe model: 2 data sockets + 1 config target_socket
// -------------------------------------------------------
#pragma pack(push, 1)
struct pcie_cfg_t {
    uint64_t base_addr_0;
    uint64_t base_addr_1;
    uint32_t max_payload;
    uint8_t  enable_mask;
    uint8_t  reserved;
};
#pragma pack(pop)

SC_MODULE(pcie_model) {
    sc_in<bool> clk;

    tlm_utils::simple_initiator_socket<pcie_model, 32, tlm::tlm_base_protocol_types, 0> sock_0;
    tlm_utils::simple_initiator_socket<pcie_model, 32, tlm::tlm_base_protocol_types, 1> sock_1;
    tlm_utils::simple_target_socket<pcie_model> cfg_socket;

    pcie_cfg_t cfg;
    sc_event cfg_event;

    SC_CTOR(pcie_model)
        : sock_0("sock_0"), sock_1("sock_1"), cfg_socket("cfg_socket")
    {
        cfg_socket.register_b_transport(this, &pcie_model::cfg_b_transport);
        SC_THREAD(run_ch0); sensitive << clk.pos();
        SC_THREAD(run_ch1); sensitive << clk.pos();
    }

    void cfg_b_transport(tlm::tlm_generic_payload& gp, sc_time& delay) {
        unsigned char* ptr = gp.get_data_ptr();
        unsigned int len = gp.get_data_length();
        if (len >= sizeof(pcie_cfg_t))
            memcpy(&cfg, ptr, sizeof(pcie_cfg_t));
        gp.set_response_status(tlm::TLM_OK_RESPONSE);
        cfg_event.notify();
    }

    void run_ch(tlm::tlm_initiator_socket<32>& sock, int ch_idx) {
        wait(cfg_event);

        uint64_t bases[2] = {bswap64(cfg.base_addr_0), bswap64(cfg.base_addr_1)};
        uint64_t base = bases[ch_idx];

        for (int i = 0; i < 12; i++) {
            unsigned char data[16];
            for (int b = 0; b < 16; b++)
                data[b] = (ch_idx * 32 + i * 16 + b) & 0xFF;
            send_gp(sock, base + i * 16, data, 16, i);
            wait();
        }
    }

    void run_ch0() { run_ch(sock_0, 0); }
    void run_ch1() { run_ch(sock_1, 1); }
};

// -------------------------------------------------------
// HBM model: 1 data socket + 1 config target_socket
// -------------------------------------------------------
#pragma pack(push, 1)
struct hbm_cfg_t {
    uint64_t base_addr;
    uint32_t burst_len;
    uint32_t channel_mode;
};
#pragma pack(pop)

SC_MODULE(hbm_model) {
    sc_in<bool> clk;

    tlm_utils::simple_initiator_socket<hbm_model> sock;
    tlm_utils::simple_target_socket<hbm_model> cfg_socket;

    hbm_cfg_t cfg;
    sc_event cfg_event;

    SC_CTOR(hbm_model) : sock("sock"), cfg_socket("cfg_socket") {
        cfg_socket.register_b_transport(this, &hbm_model::cfg_b_transport);
        SC_THREAD(run); sensitive << clk.pos();
    }

    void cfg_b_transport(tlm::tlm_generic_payload& gp, sc_time& delay) {
        unsigned char* ptr = gp.get_data_ptr();
        unsigned int len = gp.get_data_length();
        if (len >= sizeof(hbm_cfg_t))
            memcpy(&cfg, ptr, sizeof(hbm_cfg_t));
        gp.set_response_status(tlm::TLM_OK_RESPONSE);
        cfg_event.notify();
    }

    void run() {
        wait(cfg_event);

        uint64_t base = bswap64(cfg.base_addr);
        uint32_t blen = bswap32(cfg.burst_len);

        for (int i = 0; i < 8; i++) {
            unsigned char data[64];
            for (unsigned int b = 0; b < blen && b < 64; b++)
                data[b] = (i * 64 + b) & 0xFF;
            send_gp(sock, base + i * blen, data, blen, i);
            wait(); wait(); wait(); wait();
        }
    }
};

// -------------------------------------------------------
// sc_main
// -------------------------------------------------------
int sc_main(int argc, char* argv[]) {
    sc_clock clk("clk", 10, SC_NS);

    dma_model  dma("dma");
    pcie_model pcie("pcie");
    hbm_model  hbm("hbm");

    dma.clk(clk);
    pcie.clk(clk);
    hbm.clk(clk);

    // Data sockets
    sc_registry::reg("dma_0",  dma.sock_0);
    sc_registry::reg("dma_1",  dma.sock_1);
    sc_registry::reg("dma_2",  dma.sock_2);
    sc_registry::reg("pcie_0", pcie.sock_0);
    sc_registry::reg("pcie_1", pcie.sock_1);
    sc_registry::reg("hbm_0",  hbm.sock);

    // Config sockets (user's own target_socket)
    sc_registry::reg_cfg("dma_cfg",  dma.cfg_socket);
    sc_registry::reg_cfg("pcie_cfg", pcie.cfg_socket);
    sc_registry::reg_cfg("hbm_cfg",  hbm.cfg_socket);

    sc_registry::connect_all();
    sc_start(-1);
    return 0;
}
