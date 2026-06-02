// ============================================================
// Driver Callback
// ============================================================
typedef class UART_out_driver;
typedef class UART_out_sequencer;
class UART_out_driver_callback extends uvm_callback;
  `uvm_object_utils(UART_out_driver_callback)

  function new(string name = "UART_out_driver_callback");
    super.new(name);
  endfunction

  virtual function void on_pre_drive(
    UART_out_driver driver,
    UART_out_seq_item item
  );
  endfunction

  virtual function void on_post_drive(
    UART_out_driver driver,
    UART_out_seq_item item
  );
  endfunction

  virtual function void on_item_received(
    UART_out_driver driver,
    UART_out_seq_item item
  );
  endfunction

  virtual function void on_item_done(
    UART_out_driver driver,
    UART_out_seq_item item
  );
  endfunction

  virtual function void on_reset(
    UART_out_driver driver
  );
  endfunction

  virtual function void on_idle(
    UART_out_driver driver
  );
  endfunction

endclass : UART_out_driver_callback

// ============================================================
// Driver: UART_out_driver
// 场景: 异步响应/可配置延迟/背压/复位/错误恢复/统计/重试
// ============================================================

class UART_out_driver extends uvm_driver #(UART_out_seq_item);
  `uvm_component_utils(UART_out_driver)
  `uvm_register_cb(UART_out_driver, UART_out_driver_callback)

  virtual _interface vif;
  UART_out_config cfg;

  // ─── 请求队列（异步响应）───
  protected UART_out_seq_item req_queue[$];
  protected int req_id;

  // ─── 统计 ───
  protected int m_driven    = 0;
  protected int m_responded = 0;
  protected int m_retried   = 0;
  protected int m_error     = 0;
  protected realtime m_total_lat = 0;

  // ─── 状态 ───
  protected bit in_reset   = 1;
  protected bit backpressure = 0;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(UART_out_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")
    if (!uvm_config_db #(virtual _interface)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")
  endfunction

  // ─── 复位 ───
  virtual task reset_phase(uvm_phase phase);
    super.reset_phase(phase);
    in_reset = 1;
    reset_signals();
    `uvm_do_callbacks(UART_out_driver, UART_out_driver_callback, on_reset(this))
    wait(vif.presetn === 1);
    in_reset = 0;
  endtask

  virtual task reset_signals();
  endtask

  // ─── 主驱动 ───
  task run_phase(uvm_phase phase);
    fork
      get_and_drive();
      //collect_response();
      //monitor_backpressure();
    join
  endtask

  // ─── 线程1: 收请求并驱动 ───
  virtual task get_and_drive();
    forever begin
      if (in_reset) begin
        `uvm_do_callbacks(UART_out_driver, UART_out_driver_callback, on_idle(this))
        @(vif.cb);
        continue;
      end

      //wait_backpressure_release();  -- 接口信号待定义
      //sqr.throttle();               -- sqr 引用待连接
      //sqr.throttle_by_interval();   -- sqr 引用待连接

      seq_item_port.get_next_item(req);

      `uvm_do_callbacks(UART_out_driver, UART_out_driver_callback,
                        on_pre_drive(this, req))

      apply_drive_delay();

      drive_transaction(req);

      `uvm_do_callbacks(UART_out_driver, UART_out_driver_callback,
                        on_post_drive(this, req))

      req.req_id = req_id++;
      req_queue.push_back(req);
      m_driven++;
      seq_item_port.item_done();
      //sqr.inc_req();  -- sqr 引用待连接
    end
  endtask

  // ─── 线程2: 收集响应（异步+重试）───
  virtual task collect_response();
    forever begin
      wait_response_ready();

      if (req_queue.size() > 0) begin
        UART_out_seq_item req = req_queue.pop_front();

        UART_out_seq_item rsp;
        $cast(rsp, req.clone());
        rsp.set_id_info(req);
       // sample_response(rsp);

        if (rsp.error && cfg.max_retries > 0 && m_retried < cfg.max_retries) begin
          m_retried++;
          req_queue.push_front(req);  // 重新排队
          `uvm_info("DRV", $sformatf("Retry %0d/%0d", m_retried, cfg.max_retries), UVM_MEDIUM)
        end
        else begin
          realtime lat = $realtime - req.begin_time;
          m_total_lat += lat;
          m_responded++;
          seq_item_port.put_response(rsp);
        end
      end
    end
  endtask

  // ─── 线程3: 背压监测 ───
  virtual task monitor_backpressure();
    forever begin
      //@(vif.cb);
      //backpressure = (vif.cb.ready === 1'b0);
    end
  endtask

  virtual task wait_backpressure_release();
    //if (backpressure)
      //@(vif.cb iff vif.cb.ready === 1'b1);
  endtask

  // ─── 可配置延迟 ───
  virtual task apply_drive_delay();
    if (cfg.drive_delay_max > 0) begin
      //int delay = $urandom_range(cfg.drive_delay_min, cfg.drive_delay_max);
      //repeat(delay) @(vif.cb);
    end
  endtask

  virtual task drive_transaction(UART_out_seq_item req);
    @(vif.cb);
    req.begin_time = $realtime;
  endtask

  virtual task wait_response_ready();
    //@(vif.cb iff vif.cb.valid_out === 1'b1);
  endtask

  virtual function void sample_response(UART_out_seq_item rsp);
    //rsp.result = vif.cb.result;
  endfunction

  virtual function void report_phase(uvm_phase phase);
    `uvm_info("DRV", $sformatf(
      "Driver %s: driven=%0d responded=%0d retried=%0d errors=%0d avg_lat=%.1fns",
      get_full_name(), m_driven, m_responded, m_retried, m_error,
      m_responded > 0 ? m_total_lat/m_responded/1ns : 0), UVM_NONE)
  endfunction

endclass : UART_out_driver
