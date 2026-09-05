// ════════════════════════════════════════════════════════════════
// Testpoint Constraints: APB_env_tc_constraints
// 定向约束 seq_item 派生类 + 拆 seq（flow_seq）骨架
// ════════════════════════════════════════════════════════════════
// ── APB_TP_001 定向约束 ──
class APB_env_gen_test_APB_TP_001_seq_item_c extends apb_master_seq_item;
  `uvm_object_utils(APB_env_gen_test_APB_TP_001_seq_item_c)
  constraint c_tp_directed {
    paddr == 32'h1000;
    pwrite == 1;
    pwdata inside {[0:255]};
  }
endclass : APB_env_gen_test_APB_TP_001_seq_item_c

// ── APB_TP_001 拆 seq 骨架 ──
class APB_env_gen_test_APB_TP_001_flow_seq extends APB_env_virtual_base_seq;
  `uvm_object_utils(APB_env_gen_test_APB_TP_001_flow_seq)
  task body();
    // step1: apb_random_wr_seq ×10
    apb_random_wr_seq s1 = apb_random_wr_seq::type_id::create("s1");
    s1.num_transactions = 10;
    s1.start(m_sequencer);  // TODO: 按需绑定具体 bus sequencer（vsqr.<agent>_sqr）
    // step2: apb_b2b_wr_seq ×1
    apb_b2b_wr_seq s2 = apb_b2b_wr_seq::type_id::create("s2");
    s2.num_transactions = 1;
    s2.start(m_sequencer);  // TODO: 按需绑定具体 bus sequencer（vsqr.<agent>_sqr）
    // step3: apb_read_cmp_seq ×1
    apb_read_cmp_seq s3 = apb_read_cmp_seq::type_id::create("s3");
    s3.num_transactions = 1;
    s3.start(m_sequencer);  // TODO: 按需绑定具体 bus sequencer（vsqr.<agent>_sqr）
  endtask
endclass : APB_env_gen_test_APB_TP_001_flow_seq

// ── APB_TP_002 拆 seq 骨架 ──
//    [status=REVIEWED]
// class APB_env_gen_test_APB_TP_002_flow_seq extends APB_env_virtual_base_seq;
//   `uvm_object_utils(APB_env_gen_test_APB_TP_002_flow_seq)
//   task body();
//     // step1: apb_err_inject_seq ×50
//     apb_err_inject_seq s1 = apb_err_inject_seq::type_id::create("s1");
//     s1.num_transactions = 50;
//     s1.start(m_sequencer);  // TODO: 按需绑定具体 bus sequencer（vsqr.<agent>_sqr）
//   endtask
// endclass : APB_env_gen_test_APB_TP_002_flow_seq
// 
