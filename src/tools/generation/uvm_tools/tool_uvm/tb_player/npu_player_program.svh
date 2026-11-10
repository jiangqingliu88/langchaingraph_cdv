//-----------------------------------------------------------------------------
// npu_player_program.svh
//
// `commands.tsv` (playback rows) + optional `commands.json` (metadata) become
// an ordered list of npu_player_action objects.  Parsing is strictly local:
// it never touches the DUT, memory or the event bus.
//-----------------------------------------------------------------------------
`ifndef NPU_PLAYER_PROGRAM_SVH
`define NPU_PLAYER_PROGRAM_SVH

typedef enum {
  NP_ACT_HARDWARE,        // ISA / raw / external sequence op
  NP_ACT_CONTROL,         // built-in control or subclass direct extension
  NP_ACT_MEM_INIT,        // direct memory initialization
  NP_ACT_MEM_SCRUB,       // direct memory scrub
  NP_ACT_DISPATCH_MASK,   // compiler dispatch marker
  NP_ACT_DISPATCH_SKIP    // compiler dispatch-skip marker
} npu_player_action_kind;

//=============================================================================
// npu_player_action
//=============================================================================
class npu_player_action;
  int                     index;
  int                     line;
  string                  source;
  string                  op;
  npu_player_action_kind  kind;
  npu_player_json_value   params;

  bit                     has_cmddata;
  bit [73:0]              cmddata;
  bit                     instr_flag;
  bit                     has_data75;
  bit [74:0]              data75;
  bit                     skipped;

  function new();
    kind = NP_ACT_CONTROL;
    params = npu_player_json_value::make_object();
    has_cmddata = 0;
    cmddata = 74'b0;
    instr_flag = 0;
    has_data75 = 0;
    data75 = 75'b0;
    skipped = 0;
  endfunction

  function string get_string(string key, string fallback = "");
    return params == null ? fallback : params.string_or(key, fallback);
  endfunction

  function bit get_uint(string key, output longint unsigned value);
    return params != null && params.get_uint(key, value);
  endfunction

  function longint unsigned uint_or(string key, longint unsigned fallback = 0);
    return params == null ? fallback : params.uint_or(key, fallback);
  endfunction

  static function string kind_name(npu_player_action_kind kind);
    case (kind)
      NP_ACT_HARDWARE      : return "hardware";
      NP_ACT_CONTROL       : return "control";
      NP_ACT_MEM_INIT      : return "mem_init";
      NP_ACT_MEM_SCRUB     : return "mem_scrub";
      NP_ACT_DISPATCH_MASK : return "dispatch_mask";
      NP_ACT_DISPATCH_SKIP : return "dispatch_skip";
      default              : return "unknown";
    endcase
  endfunction
endclass

//=============================================================================
// npu_player_program
//=============================================================================
class npu_player_program;
  npu_player_action actions[$];
  string            base_dir;
  string            source_path;

  function npu_player_action by_index(int index_value);
    foreach (actions[i]) if (actions[i].index == index_value) return actions[i];
    return null;
  endfunction

  // commands.json stores the canonical control-row spelling ("wait done");
  // commands.tsv and this player use the underscore form.
  static function string normalize_op(string op);
    case (op)
      "wait cycles" : return "wait_cycles";
      "wait done"   : return "wait_done";
      "wait event"  : return "wait_event";
      "signal event": return "signal_event";
      "raw cmd"     : return "raw_cmd";
      "expect rd"   : return "expect_rd";
      "expect write": return "expect_write";
      "expect region": return "expect_region";
      "expect intr" : return "expect_intr";
      "expect idle" : return "expect_idle";
      "expect perf" : return "expect_perf";
      "perf window" : return "perf_window";
      default       : return op;
    endcase
  endfunction

  static function bit is_builtin_control(string op);
    op = normalize_op(op);
    return op inside {"wait_cycles", "wait_done", "wait_event", "signal_event",
                      "nop", "watchdog", "checkpoint", "batch_begin", "batch_end"};
  endfunction

  static function bit is_control_like(string op);
    op = normalize_op(op);
    return op inside {"wait_cycles", "wait_done", "wait_event", "signal_event",
                      "nop", "watchdog", "checkpoint", "batch_begin", "batch_end",
                      "expect_rd", "expect_write", "expect_region", "expect_intr",
                      "expect_idle", "expect_perf", "perf_window",
                      "set", "intr_ack", "peer_cfg", "dram_cfg",
                      "spawn_async", "reset", "pwr_ctl"};
  endfunction

  static function npu_player_action_kind classify(string op);
    op = normalize_op(op);
    if (op == "mem_init")       return NP_ACT_MEM_INIT;
    if (op == "mem_scrub")      return NP_ACT_MEM_SCRUB;
    if (op == "dispatch_mask")  return NP_ACT_DISPATCH_MASK;
    if (op == "dispatch_skip")  return NP_ACT_DISPATCH_SKIP;
    if (is_control_like(op))    return NP_ACT_CONTROL;
    return NP_ACT_HARDWARE;     // ISA op / raw cmd / csr_* / external op
  endfunction

  //---------------------------------------------------------------------------
  // commands.tsv
  //---------------------------------------------------------------------------
  function bit scan(string path, int unsigned max_file_bytes,
                    int unsigned max_actions, output string err);
    int fd;
    string line;
    int unsigned bytes_read;
    int physical_line;

    actions.delete();
    source_path = path;
    base_dir = dirname(path);
    fd = $fopen(path, "r");
    if (fd == 0) begin
      err = {"cannot open commands file: ", path};
      return 0;
    end
    bytes_read = 0;
    physical_line = 0;
    while ($fgets(line, fd) > 0) begin
      physical_line++;
      bytes_read += line.len();
      if (bytes_read > max_file_bytes) begin
        $fclose(fd);
        err = $sformatf("commands file exceeds max_file_bytes (%0d)", max_file_bytes);
        return 0;
      end
      line = npu_player_text::trim(npu_player_text::strip_eol(line));
      if (line == "" || npu_player_text::starts_with(line, "//") ||
          npu_player_text::starts_with(line, "#")) continue;
      if (!parse_row(line, physical_line, err)) begin
        $fclose(fd);
        return 0;
      end
      if (actions.size() > max_actions) begin
        $fclose(fd);
        err = $sformatf("too many actions (max %0d)", max_actions);
        return 0;
      end
    end
    $fclose(fd);
    if (actions.size() == 0) begin
      err = "commands file contains no actions";
      return 0;
    end
    // Sequential defaults for rows that carried no compiler index.
    foreach (actions[i]) if (actions[i].index < 0) actions[i].index = i;
    err = "";
    return 1;
  endfunction

  protected function bit parse_row(string line, int physical_line, output string err);
    string parts[$];
    npu_player_action action;
    action = new();
    action.index = -1;
    action.line = physical_line;
    action.source = line;
    npu_player_text::split_tabs(line, parts);

    if (parts.size() == 4) begin
      // dispatch_mask/dispatch_skip\t{json}\tsource_line\tsource_isa
      npu_player_json_parser parser = new(parts[1]);
      action.op = parts[0];
      action.params = parser.parse();
      if (!parser.ok() || action.params == null) begin
        err = $sformatf("line %0d: dispatch parameters are not valid JSON", physical_line);
        return 0;
      end
      if (npu_player_text::is_uint_token(parts[2])) action.line = parts[2].atoi();
      action.source = parts[3];
      action.kind = classify(action.op);
    end
    else if (parts.size() == 3) begin
      int digits;
      if (npu_player_text::is_uint_token(parts[0])) begin
        // <index>\t<source_line>\t<source_isa>
        action.index = parts[0].atoi();
        if (npu_player_text::is_uint_token(parts[1])) action.line = parts[1].atoi();
        action.source = parts[2];
        if (!parse_source(action, parts[2], physical_line, err)) return 0;
      end
      else if (npu_player_text::is_hex_token(parts[0], digits) &&
               npu_player_text::is_uint_token(parts[1])) begin
        // <cmddata>\t<source_line>\t<source_isa> (pre-resolved playback row)
        bit [73:0] raw_data;
        if (!npu_player_text::parse_cmddata(parts[0], raw_data)) begin
          err = $sformatf("line %0d: cmddata does not fit 74 bits", physical_line);
          return 0;
        end
        action.has_cmddata = 1;
        action.cmddata = raw_data;
        action.line = parts[1].atoi();
        action.source = parts[2];
        if (!parse_source(action, parts[2], physical_line, err)) return 0;
        action.kind = NP_ACT_HARDWARE;
      end
      else begin
        err = $sformatf("line %0d: unrecognized 3-column command row", physical_line);
        return 0;
      end
    end
    else if (parts.size() == 2) begin
      action.op = parts[0];
      if (!set_body(action, parts[1], physical_line, err)) return 0;
    end
    else if (parts.size() == 1) begin
      action.op = parts[0];
      action.params = npu_player_json_value::make_object();
      action.kind = classify(action.op);
    end
    else begin
      err = $sformatf("line %0d: expected 1-4 tab-separated columns", physical_line);
      return 0;
    end

    if (action.op == "") begin
      err = $sformatf("line %0d: empty operation", physical_line);
      return 0;
    end
    actions.push_back(action);
    return 1;
  endfunction

  protected function bit parse_source(npu_player_action action, string source,
                                      int physical_line, output string err);
    string parts[$];
    int split_at;
    source = npu_player_text::trim(source);
    split_at = -1;
    for (int i = 0; i < source.len(); i++) begin
      if (source[i] == 8'h20 || source[i] == 8'h09) begin
        split_at = i;
        break;
      end
    end
    if (split_at < 0) begin
      action.op = source;
      action.params = npu_player_json_value::make_object();
      action.kind = classify(action.op);
      return 1;
    end
    action.op = source.substr(0, split_at - 1);
    return set_body(action, source.substr(split_at + 1, source.len() - 1),
                    physical_line, err);
  endfunction

  protected function bit set_body(npu_player_action action, string body,
                                  int physical_line, output string err);
    npu_player_json_value parsed;
    body = npu_player_text::trim(body);
    if (body != "" && body[0] == "{") begin
      npu_player_json_parser parser = new(body);
      parsed = parser.parse();
      if (!parser.ok() || parsed == null) begin
        err = $sformatf("line %0d: bad parameter object: %s",
                        physical_line, parser.error());
        return 0;
      end
    end
    else begin
      parsed = npu_player_kv_parser::parse(body);
      if (parsed == null) begin
        err = $sformatf("line %0d: %s", physical_line, npu_player_kv_parser::last_error);
        return 0;
      end
    end
    action.params = parsed;
    action.kind = classify(action.op);
    // A `key=value` body after `raw cmd` can carry the hardware container.
    if (action.op == "raw cmd" || action.op == "raw_cmd") begin
      string command_text;
      bit flag_value;
      bit [73:0] raw_data;
      action.kind = NP_ACT_HARDWARE;
      action.op = "raw_cmd";
      if (parsed.get_string("cmddata", command_text)) begin
        if (!npu_player_text::parse_cmddata(command_text, raw_data)) begin
          err = $sformatf("line %0d: raw cmddata does not fit 74 bits", physical_line);
          return 0;
        end
        action.has_cmddata = 1;
        action.cmddata = raw_data;
      end
      if (parsed.get_bit("instr_flag", flag_value)) action.instr_flag = flag_value;
    end
    return 1;
  endfunction

  //---------------------------------------------------------------------------
  // commands.json
  //---------------------------------------------------------------------------
  function bit attach_metadata(string path, int unsigned max_file_bytes,
                               output string err);
    int fd;
    string chunk, text;
    int unsigned bytes_read;
    npu_player_json_parser parser;
    npu_player_json_value root, records;
    npu_player_json_value record;

    if (path == "-" || path == "") begin
      err = "";
      return 1;
    end
    fd = $fopen(path, "r");
    if (fd == 0) begin
      err = {"cannot open metadata file: ", path};
      return 0;
    end
    text = "";
    bytes_read = 0;
    while ($fgets(chunk, fd) > 0) begin
      bytes_read += chunk.len();
      if (bytes_read > max_file_bytes) begin
        $fclose(fd);
        err = $sformatf("metadata file exceeds max_file_bytes (%0d)", max_file_bytes);
        return 0;
      end
      text = {text, chunk};
    end
    $fclose(fd);

    parser = new(text);
    root = parser.parse();
    if (!parser.ok() || root == null || !root.is_object()) begin
      err = {"metadata is not a JSON object: ", parser.error()};
      return 0;
    end
    records = root.get("commands");
    if (records == null || !records.is_array()) begin
      err = "metadata has no commands array";
      return 0;
    end
    foreach (records.array_value[i]) begin
      record = records.array_value[i];
      if (record == null || !record.is_object()) begin
        err = $sformatf("metadata commands[%0d] is not an object", i);
        return 0;
      end
      if (!merge_record(record, err)) return 0;
    end
    err = "";
    return 1;
  endfunction

  protected function bit merge_record(npu_player_json_value record, output string err);
    longint index_value;
    npu_player_action action;
    string text_value;
    string cmddata_text;
    bit have_cmddata;
    npu_player_json_value parameters;
    npu_player_json_value cmddata_value;

    if (!record.get_longint("index", index_value)) begin
      err = "metadata command is missing an integer index";
      return 0;
    end
    action = by_index(int'(index_value));
    if (action == null) begin
      err = $sformatf("metadata index %0d has no matching playback row", index_value);
      return 0;
    end
    if (record.get_string("op", text_value))    action.op = normalize_op(text_value);
    if (record.get_string("source_isa", text_value) && text_value != "")
      action.source = text_value;
    if (record.get_string("kind", text_value)) begin
      if (text_value == "instruction") action.kind = NP_ACT_HARDWARE;
      else if (text_value == "control") action.kind = classify(action.op);
    end
    parameters = record.get("parameters");
    if (parameters != null && parameters.is_object()) begin
      if (action.params == null) action.params = npu_player_json_value::make_object();
      action.params.merge_object(parameters);
    end
    if (record.get_string("passthrough", text_value) && text_value != "") begin
      if (npu_player_text::starts_with(text_value, action.op)) begin
        if (!set_body(action, text_value.substr(action.op.len(), text_value.len() - 1),
                      action.line, err)) return 0;
      end
    end
    have_cmddata = record.get_string("cmddata", cmddata_text);
    if (!have_cmddata) begin
      cmddata_value = record.get("cmddata");
      if (cmddata_value != null && cmddata_value.kind == NP_JV_STRING) begin
        cmddata_text = cmddata_value.string_value;
        have_cmddata = 1;
      end
    end
    if (have_cmddata && cmddata_text != "") begin
      bit [73:0] raw_data;
      if (!npu_player_text::parse_cmddata(cmddata_text, raw_data)) begin
        err = $sformatf("metadata index %0d has invalid cmddata", index_value);
        return 0;
      end
      action.has_cmddata = 1;
      action.cmddata = raw_data;
    end
    begin
      longint flag_value;
      if (record.get_longint("instr_flag", flag_value)) action.instr_flag = (flag_value != 0);
    end
    begin
      npu_player_json_value data75_value = record.get("data75");
      string data75_text;
      bit [74:0] raw75;
      if (data75_value != null && data75_value.kind == NP_JV_STRING)
        data75_text = data75_value.string_value;
      else if (data75_value != null && data75_value.kind == NP_JV_INT)
        data75_text = $sformatf("%0h", data75_value.int_value);
      if (data75_text != "") begin
        if (!npu_player_text::parse_data75(data75_text, raw75)) begin
          err = $sformatf("metadata index %0d has invalid data75", index_value);
          return 0;
        end
        action.has_data75 = 1;
        action.data75 = raw75;
      end
    end
    if (action.op == "mem_init")       action.kind = NP_ACT_MEM_INIT;
    if (action.op == "mem_scrub")      action.kind = NP_ACT_MEM_SCRUB;
    if (action.op == "dispatch_mask")  action.kind = NP_ACT_DISPATCH_MASK;
    if (action.op == "dispatch_skip")  action.kind = NP_ACT_DISPATCH_SKIP;
    err = "";
    return 1;
  endfunction

  static function string dirname(string path);
    for (int i = path.len() - 1; i >= 0; i--) begin
      if (path[i] == "/" || path[i] == "\\")
        return path.substr(0, i - 1);
    end
    return ".";
  endfunction
endclass

`endif // NPU_PLAYER_PROGRAM_SVH
