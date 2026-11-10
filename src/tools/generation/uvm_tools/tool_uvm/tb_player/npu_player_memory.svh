//-----------------------------------------------------------------------------
// npu_player_memory.svh
//
// Direct memory operations (`mem_init` / `mem_scrub`) and the abstract memory
// backend the env injects.  The base player never imports a concrete memory
// model: an unbound backend fails loudly instead of silently doing nothing.
//-----------------------------------------------------------------------------
`ifndef NPU_PLAYER_MEMORY_SVH
`define NPU_PLAYER_MEMORY_SVH

class npu_player_mem_result;
  bit    ok;
  string phase;
  string handle;
  string error;

  static function npu_player_mem_result success(string phase, string handle = "");
    npu_player_mem_result result = new();
    result.ok = 1;
    result.phase = phase;
    result.handle = handle;
    result.error = "";
    return result;
  endfunction

  static function npu_player_mem_result failure(string error);
    npu_player_mem_result result = new();
    result.ok = 0;
    result.phase = "";
    result.handle = "";
    result.error = error;
    return result;
  endfunction
endclass

//=============================================================================
// npu_player_mem_init - resolved mem_init parameters
//=============================================================================
class npu_player_mem_init;
  string              ref_name;
  string              source_tensor;
  string              region;
  string              address_kind;
  string              path;
  string              file;
  string              format;
  longint unsigned    base;
  int unsigned        shape[3];
  string              dtype;
  int unsigned        element_bits;
  string              byte_order;
  longint unsigned    file_offset_bytes;
  longint unsigned    file_row_stride_bytes;
  longint unsigned    file_plane_stride_bytes;
  longint unsigned    dst_row_stride_bytes;
  longint unsigned    dst_plane_stride_bytes;
  longint unsigned    copy_row_bytes;
  longint unsigned    copy_bytes;
  longint unsigned    span_bytes;
  longint unsigned    payload_bytes;
  longint unsigned    file_size_bytes;
  string              file_sha256;
  string              content_sha256;
  string              tail_policy;
  string              gap_policy;
  bit                 has_file;

  function new();
    base = 0;
    shape = '{1, 1, 1};
    element_bits = 0;
    file_offset_bytes = 0;
    file_row_stride_bytes = 0;
    file_plane_stride_bytes = 0;
    dst_row_stride_bytes = 0;
    dst_plane_stride_bytes = 0;
    copy_row_bytes = 0;
    copy_bytes = 0;
    span_bytes = 0;
    payload_bytes = 0;
    file_size_bytes = 0;
    has_file = 0;
  endfunction

  function bit from_action(npu_player_action action, string base_dir, output string err);
    npu_player_json_value p = action.params;
    npu_player_json_value shape_value;
    longint unsigned value;
    if (p == null || !p.is_object()) begin
      err = "mem_init has no parameter object";
      return 0;
    end
    ref_name          = p.string_or("ref");
    source_tensor     = p.string_or("source_tensor");
    region            = p.string_or("region");
    address_kind      = p.string_or("address_kind", "global48");
    path              = p.string_or("path", "backdoor");
    file              = p.string_or("file");
    format            = p.string_or("format", "bin");
    dtype             = p.string_or("dtype");
    byte_order        = p.string_or("byte_order", "little");
    file_sha256       = p.string_or("file_sha256");
    content_sha256    = p.string_or("content_sha256");
    tail_policy       = p.string_or("tail_policy", "zero");
    gap_policy        = p.string_or("gap_policy", "untouched");
    if (!p.get_uint("base", value) && !p.get_uint("address", value)) begin
      err = "mem_init requires a numeric base/address";
      return 0;
    end
    base = value;
    file_offset_bytes = p.uint_or("file_offset_bytes", 0);
    file_row_stride_bytes = p.uint_or("file_row_stride_bytes", 0);
    file_plane_stride_bytes = p.uint_or("file_plane_stride_bytes", 0);
    dst_row_stride_bytes = p.uint_or("dst_row_stride_bytes", 0);
    dst_plane_stride_bytes = p.uint_or("dst_plane_stride_bytes", 0);
    copy_row_bytes = p.uint_or("copy_row_bytes", 0);
    copy_bytes = p.uint_or("copy_bytes", 0);
    span_bytes = p.uint_or("span_bytes", 0);
    payload_bytes = p.uint_or("payload_bytes", 0);
    file_size_bytes = p.uint_or("file_size_bytes", 0);
    element_bits = p.uint_or("element_bits", 0);
    shape_value = p.get("shape");
    if (shape_value != null && shape_value.is_array()) begin
      int dims = shape_value.size();
      if (dims > 3) dims = 3;
      for (int i = 0; i < dims; i++) shape[i] = shape_value.index(i).int_value;
      for (int i = dims; i < 3; i++) shape[i] = 1;
    end
    if (region == "") begin
      err = "mem_init requires a region";
      return 0;
    end
    if (file != "") begin
      has_file = 1;
      if (!is_absolute(file)) file = join_path(base_dir, file);
    end
    if (path == "backdoor" && has_file && format != "bin" && format != "hex") begin
      err = {"mem_init format must be bin or hex, got ", format};
      return 0;
    end
    err = "";
    return 1;
  endfunction

  static function bit is_absolute(string path);
    if (path.len() == 0) return 0;
    if (path[0] == "/" || path[0] == "\\") return 1;
    if (path.len() > 1 && path[1] == ":") return 1;
    return 0;
  endfunction

  static function string join_path(string dir, string name);
    if (dir == "" || dir == ".") return name;
    if (dir[dir.len() - 1] == "/" || dir[dir.len() - 1] == "\\")
      return {dir, name};
    return {dir, "/", name};
  endfunction
endclass

//=============================================================================
// npu_player_mem_scrub
//=============================================================================
class npu_player_mem_scrub;
  string           region;
  string           address_kind;
  string           path;
  longint unsigned base;
  longint unsigned size_bytes;
  longint unsigned pattern;

  function bit from_action(npu_player_action action, output string err);
    npu_player_json_value p = action.params;
    longint unsigned value;
    if (p == null || !p.is_object()) begin
      err = "mem_scrub has no parameter object";
      return 0;
    end
    region       = p.string_or("region");
    address_kind = p.string_or("address_kind", "global48");
    path         = p.string_or("path", "backdoor");
    if (!p.get_uint("base", value) && !p.get_uint("address", value)) begin
      err = "mem_scrub requires a numeric base/address";
      return 0;
    end
    base = value;
    if (!p.get_uint("size_bytes", value) && !p.get_uint("size", value)) begin
      err = "mem_scrub requires size_bytes";
      return 0;
    end
    size_bytes = value;
    pattern = p.uint_or("pattern", 0);
    if (region == "") begin
      err = "mem_scrub requires a region";
      return 0;
    end
    err = "";
    return 1;
  endfunction
endclass

//=============================================================================
// npu_player_memory_if - injected by env; the player package stays independent
//=============================================================================
virtual class npu_player_memory_if;
  pure virtual task init(npu_player_mem_init request, output npu_player_mem_result result);
  pure virtual task scrub(npu_player_mem_scrub request, output npu_player_mem_result result);
endclass

//=============================================================================
// npu_player_memory_stub - default backend: every direct op is BLOCKED
//=============================================================================
class npu_player_memory_stub extends npu_player_memory_if;
  virtual task init(npu_player_mem_init request, output npu_player_mem_result result);
    result = npu_player_mem_result::failure(
        "no memory backend bound: connect_memory() before play()");
  endtask

  virtual task scrub(npu_player_mem_scrub request, output npu_player_mem_result result);
    result = npu_player_mem_result::failure(
        "no memory backend bound: connect_memory() before play()");
  endtask
endclass

`endif // NPU_PLAYER_MEMORY_SVH
