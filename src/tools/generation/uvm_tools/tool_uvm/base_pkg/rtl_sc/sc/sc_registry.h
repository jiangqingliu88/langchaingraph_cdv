#ifndef SC_REGISTRY_H
#define SC_REGISTRY_H

#include <systemc.h>
#include <tlm.h>
#include <string>
#include <vector>
#include <functional>

#include "uvmc.h"
using namespace uvmc;

// SC-side one-line registration API.
//
// Data channel:
//   sc_registry::reg("dma_0", my_module.data_socket);
//
// Config channel (user's own target_socket, user parses bytes themselves):
//   sc_registry::reg_cfg("dma_cfg", my_module.cfg_socket);
//
// Connect:
//   sc_registry::connect_all();

class sc_registry {
public:
    // Register data channel (user's initiator_socket)
    template<typename SOCKET_T>
    static void reg(const std::string& id, SOCKET_T& socket) {
        entry e;
        e.lookup = "rtl_sc_" + id;
        e.ptr = (void*)&socket;
        e.fn = [](void* p, const std::string& lk) {
            SOCKET_T& s = *(SOCKET_T*)p;
            uvmc_connect(s, lk);
        };
        entries().push_back(e);
    }

    // Register config channel (user's target_socket, user handles b_transport)
    template<typename SOCKET_T>
    static void reg_cfg(const std::string& id, SOCKET_T& socket) {
        entry e;
        e.lookup = "rtl_sc_cfg_" + id;
        e.ptr = (void*)&socket;
        e.fn = [](void* p, const std::string& lk) {
            SOCKET_T& s = *(SOCKET_T*)p;
            uvmc_connect(s, lk);
        };
        entries().push_back(e);
    }

    // Connect all registered sockets. Call before sc_start().
    static void connect_all() {
        for (auto& e : entries()) {
            e.fn(e.ptr, e.lookup);
        }
    }

private:
    typedef std::function<void(void*, const std::string&)> connect_fn_t;

    struct entry {
        std::string lookup;
        void* ptr;
        connect_fn_t fn;
    };

    static std::vector<entry>& entries() {
        static std::vector<entry> v;
        return v;
    }
};

#endif
