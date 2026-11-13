//-----------------------------------------------------------------------------
// npu_player_value.svh
//
// Bottom layer of the standalone playback player: a tiny JSON value/parser,
// a `key=value` parser used by commands.tsv, and the text/raw helpers shared
// by the program and player layers.
//
// This package deliberately has no knowledge of UVM, env, agents or memory.
//-----------------------------------------------------------------------------
`ifndef NPU_PLAYER_VALUE_SVH
`define NPU_PLAYER_VALUE_SVH

typedef enum {
  NP_JV_NULL,
  NP_JV_BOOL,
  NP_JV_INT,
  NP_JV_REAL,
  NP_JV_STRING,
  NP_JV_ARRAY,
  NP_JV_OBJECT
} npu_player_json_kind;

//=============================================================================
// npu_player_text - small string helpers (no regex dependency)
//=============================================================================
class npu_player_text;
  static function string trim(string value);
    int lo, hi;
    lo = 0;
    hi = value.len() - 1;
    while (lo <= hi && (value[lo] == " " || value[lo] == 9)) lo++;
    while (hi >= lo && (value[hi] == " " || value[hi] == 9 ||
                        value[hi] == 10 || value[hi] == 13)) hi--;
    return (lo > hi) ? "" : value.substr(lo, hi);
  endfunction

  static function string strip_eol(string value);
    int hi;
    hi = value.len() - 1;
    while (hi >= 0 && (value[hi] == 10 || value[hi] == 13)) hi--;
    return (hi < 0) ? "" : value.substr(0, hi);
  endfunction

  static function bit starts_with(string value, string prefix);
    return value.len() >= prefix.len() && value.substr(0, prefix.len() - 1) == prefix;
  endfunction

  static function void split_tabs(string value, ref string parts[$]);
    string piece;
    parts.delete();
    piece = "";
    foreach (value[i]) begin
      if (value[i] == 9) begin
        parts.push_back(trim(piece));
        piece = "";
      end
      else begin
        piece = {piece, value[i]};
      end
    end
    parts.push_back(trim(piece));
  endfunction

  static function bit is_uint_token(string value);
    if (value.len() == 0) return 0;
    foreach (value[i]) begin
      if (value[i] < "0" || value[i] > "9") return 0;
    end
    return 1;
  endfunction

  static function bit is_hex_token(string value, output int width_digits);
    int start;
    width_digits = 0;
    if (value.len() == 0) return 0;
    start = 0;
    if (value.len() > 2 && value.substr(0, 1) == "0x") start = 2;
    else if (value.len() > 2 && value.substr(0, 1) == "0X") start = 2;
    if (start >= value.len()) return 0;
    for (int i = start; i < value.len(); i++) begin
      byte c = value[i];
      if (!((c >= "0" && c <= "9") || (c >= "a" && c <= "f") ||
            (c >= "A" && c <= "F"))) return 0;
      width_digits++;
    end
    return width_digits > 0;
  endfunction

  // Parse an unsigned integer written as decimal or 0x-hex.
  static function longint unsigned to_uint(string value, output bit ok);
    longint unsigned result;
    int start;
    result = 0;
    ok = 0;
    value = trim(value);
    if (value.len() == 0) return 0;
    start = 0;
    if (value.len() > 2 && (value.substr(0, 1) == "0x" || value.substr(0, 1) == "0X"))
      start = 2;
    for (int i = start; i < value.len(); i++) begin
      byte c = value[i];
      int digit;
      if (c >= "0" && c <= "9")      digit = c - "0";
      else if (c >= "a" && c <= "f") digit = c - "a" + 10;
      else if (c >= "A" && c <= "F") digit = c - "A" + 10;
      else return 0;
      if ((result >> 60) != 0) return 0;   // keep the math 64-bit safe
      result = (result << 4) + digit;
    end
    ok = 1;
    return result;
  endfunction

  static function bit parse_cmddata(string value, output bit [73:0] data);
    int digits;
    int start;
    data = 74'b0;
    if (!is_hex_token(value, digits)) return 0;
    if (digits > 19) return 0;
    start = (value.len() > 2 && (value.substr(0, 1) == "0x" || value.substr(0, 1) == "0X")) ? 2 : 0;
    for (int i = start; i < value.len(); i++) begin
      byte c = value[i];
      bit [3:0] digit;
      if (c >= "0" && c <= "9")      digit = c - "0";
      else if (c >= "a" && c <= "f") digit = c - "a" + 10;
      else if (c >= "A" && c <= "F") digit = c - "A" + 10;
      else return 0;
      // 74 bits = eighteen full nibbles plus two low bits.
      if (data[73:70] != 4'b0) return 0;
      data = (data << 4) | digit;
    end
    return 1;
  endfunction

  static function bit parse_data75(string value, output bit [74:0] data);
    int digits;
    int start;
    data = 75'b0;
    if (!is_hex_token(value, digits) || digits > 19) return 0;
    start = (value.len() > 2 && (value.substr(0, 1) == "0x" || value.substr(0, 1) == "0X")) ? 2 : 0;
    for (int i = start; i < value.len(); i++) begin
      byte c = value[i];
      bit [3:0] digit;
      if (c >= "0" && c <= "9")      digit = c - "0";
      else if (c >= "a" && c <= "f") digit = c - "a" + 10;
      else if (c >= "A" && c <= "F") digit = c - "A" + 10;
      else return 0;
      if (data[74:71] != 4'b0) return 0;
      data = (data << 4) | digit;
    end
    return 1;
  endfunction

  // Split at top-level commas: quotes and (), [], {} shield separators.
  static function void split_top(string value, ref string parts[$]);
    string piece;
    int depth;
    byte quote;
    parts.delete();
    piece = "";
    depth = 0;
    quote = 0;
    foreach (value[i]) begin
      byte c = value[i];
      if (quote != 0) begin
        piece = {piece, c};
        if (c == quote) quote = 0;
        continue;
      end
      if (c == "\"" || c == "'") begin
        quote = c;
        piece = {piece, c};
      end
      else if (c == "{" || c == "[" || c == "(") begin
        depth++;
        piece = {piece, c};
      end
      else if (c == "}" || c == "]" || c == ")") begin
        depth--;
        piece = {piece, c};
      end
      else if (c == "," && depth == 0) begin
        parts.push_back(trim(piece));
        piece = "";
      end
      else begin
        piece = {piece, c};
      end
    end
    if (trim(piece) != "") parts.push_back(trim(piece));
  endfunction

  // First top-level '=' (or ':' when the item has no '=').
  static function int split_assignment(string item, output string key, output string raw);
    int depth;
    byte quote;
    int separator;
    depth = 0;
    quote = 0;
    separator = -1;
    foreach (item[i]) begin
      byte c = item[i];
      if (quote != 0) begin
        if (c == quote) quote = 0;
        continue;
      end
      if (c == "\"" || c == "'") quote = c;
      else if (c == "{" || c == "[" || c == "(") depth++;
      else if (c == "}" || c == "]" || c == ")") depth--;
      else if (depth == 0 && c == "=") begin
        separator = i;
        break;
      end
    end
    if (separator < 0) begin
      foreach (item[i]) begin
        if (item[i] == ":" && depth == 0) begin
          separator = i;
          break;
        end
      end
    end
    if (separator < 0) begin
      key = "";
      raw = trim(item);
      return 0;
    end
    key = trim(item.substr(0, separator - 1));
    raw = trim(item.substr(separator + 1, item.len() - 1));
    return (key.len() > 0 && raw.len() > 0) ? 1 : 0;
  endfunction
endclass

//=============================================================================
// npu_player_json_value - a minimally typed JSON tree
//=============================================================================
class npu_player_json_value;
  npu_player_json_kind kind;
  bit                  bool_value;
  longint              int_value;
  real                 real_value;
  string               string_value;
  npu_player_json_value array_value[$];
  npu_player_json_value object_value[string];

  function new(npu_player_json_kind k = NP_JV_NULL);
    kind = k;
  endfunction

  static function npu_player_json_value make_null();
    npu_player_json_value v = new(NP_JV_NULL);
    return v;
  endfunction

  static function npu_player_json_value make_bool(bit value);
    npu_player_json_value v = new(NP_JV_BOOL);
    v.bool_value = value;
    return v;
  endfunction

  static function npu_player_json_value make_int(longint value);
    npu_player_json_value v = new(NP_JV_INT);
    v.int_value = value;
    return v;
  endfunction

  static function npu_player_json_value make_real(real value);
    npu_player_json_value v = new(NP_JV_REAL);
    v.real_value = value;
    return v;
  endfunction

  static function npu_player_json_value make_string(string value);
    npu_player_json_value v = new(NP_JV_STRING);
    v.string_value = value;
    return v;
  endfunction

  static function npu_player_json_value make_array();
    npu_player_json_value v = new(NP_JV_ARRAY);
    return v;
  endfunction

  static function npu_player_json_value make_object();
    npu_player_json_value v = new(NP_JV_OBJECT);
    return v;
  endfunction

  function bit is_object();
    return kind == NP_JV_OBJECT;
  endfunction

  function bit is_array();
    return kind == NP_JV_ARRAY;
  endfunction

  function bit has(string key);
    return kind == NP_JV_OBJECT && object_value.exists(key);
  endfunction

  function npu_player_json_value get(string key);
    if (kind == NP_JV_OBJECT && object_value.exists(key))
      return object_value[key];
    return null;
  endfunction

  function void put(string key, npu_player_json_value value);
    if (kind != NP_JV_OBJECT) return;
    if (value == null) object_value[key] = new(NP_JV_NULL);
    else object_value[key] = value;
  endfunction

  function int size();
    if (kind == NP_JV_ARRAY) return array_value.size();
    if (kind == NP_JV_OBJECT) return object_value.size();
    return 0;
  endfunction

  function npu_player_json_value index(int idx);
    if (kind == NP_JV_ARRAY && idx >= 0 && idx < array_value.size())
      return array_value[idx];
    return null;
  endfunction

  function bit get_string(string key, output string value);
    npu_player_json_value v = get(key);
    if (v == null || v.kind != NP_JV_STRING) return 0;
    value = v.string_value;
    return 1;
  endfunction

  function string string_or(string key, string fallback = "");
    string value;
    return get_string(key, value) ? value : fallback;
  endfunction

  function bit get_longint(string key, output longint value);
    npu_player_json_value v = get(key);
    if (v == null) return 0;
    if (v.kind == NP_JV_INT) begin
      value = v.int_value;
      return 1;
    end
    if (v.kind == NP_JV_REAL) begin
      value = longint'(v.real_value);
      return 1;
    end
    return 0;
  endfunction

  function bit get_uint(string key, output longint unsigned value);
    longint signed_value;
    if (!get_longint(key, signed_value) || signed_value < 0) return 0;
    value = $unsigned(signed_value);
    return 1;
  endfunction

  function bit get_bit(string key, output bit value);
    npu_player_json_value v = get(key);
    if (v == null) return 0;
    if (v.kind == NP_JV_BOOL) begin
      value = v.bool_value;
      return 1;
    end
    if (v.kind == NP_JV_INT) begin
      value = (v.int_value != 0);
      return 1;
    end
    return 0;
  endfunction

  function longint unsigned uint_or(string key, longint unsigned fallback = 0);
    longint unsigned value;
    return get_uint(key, value) ? value : fallback;
  endfunction

  function void merge_object(npu_player_json_value source);
    if (source == null || source.kind != NP_JV_OBJECT) return;
    foreach (source.object_value[key]) put(key, source.object_value[key]);
  endfunction
endclass

//=============================================================================
// npu_player_json_parser - a strict-enough JSON reader for commands.json
//=============================================================================
class npu_player_json_parser;
  protected string text;
  protected int    pos;
  protected bit    failed;
  protected string failure;

  function new(string text);
    this.text = text;
    this.pos = 0;
    this.failed = 0;
    this.failure = "";
  endfunction

  function bit ok();
    return !failed;
  endfunction

  function string error();
    return failure;
  endfunction

  function npu_player_json_value parse();
    npu_player_json_value value;
    skip_ws();
    value = parse_value();
    skip_ws();
    if (!failed && pos != text.len()) fail("trailing characters after JSON value");
    return failed ? null : value;
  endfunction

  protected function void fail(string message);
    if (!failed) begin
      failed = 1;
      failure = message;
    end
  endfunction

  protected function void skip_ws();
    while (pos < text.len()) begin
      byte c = text[pos];
      if (c == " " || c == 9 || c == 10 || c == 13) pos++;
      else break;
    end
  endfunction

  protected function npu_player_json_value parse_value();
    npu_player_json_value value;
    skip_ws();
    if (pos >= text.len()) begin
      fail("unexpected end of JSON");
      return null;
    end
    case (text[pos])
      "{" : return parse_object();
      "[" : return parse_array();
      "\"": return npu_player_json_value::make_string(parse_string());
      "t" : if (match("true"))  return npu_player_json_value::make_bool(1);
      "f" : if (match("false")) return npu_player_json_value::make_bool(0);
      "n" : if (match("null"))  return npu_player_json_value::make_null();
      default: return parse_number();
    endcase
    fail("unexpected token");
    return null;
  endfunction

  protected function bit match(string literal);
    if (pos + literal.len() > text.len()) return 0;
    if (text.substr(pos, pos + literal.len() - 1) != literal) return 0;
    pos += literal.len();
    return 1;
  endfunction

  protected function npu_player_json_value parse_object();
    npu_player_json_value object_value = npu_player_json_value::make_object();
    string key;
    skip_ws();
    pos++; // {
    skip_ws();
    if (pos < text.len() && text[pos] == "}") begin pos++; return object_value; end
    forever begin
      skip_ws();
      if (pos >= text.len() || text[pos] != "\"") begin
        fail("object key must be a string");
        return null;
      end
      key = parse_string();
      skip_ws();
      if (pos >= text.len() || text[pos] != ":") begin
        fail("expected ':' after object key");
        return null;
      end
      pos++;
      object_value.put(key, parse_value());
      if (failed) return null;
      skip_ws();
      if (pos >= text.len()) begin fail("unterminated object"); return null; end
      if (text[pos] == ",") begin pos++; continue; end
      if (text[pos] == "}") begin pos++; return object_value; end
      fail("expected ',' or '}' in object");
      return null;
    end
  endfunction

  protected function npu_player_json_value parse_array();
    npu_player_json_value array_value = npu_player_json_value::make_array();
    skip_ws();
    pos++; // [
    skip_ws();
    if (pos < text.len() && text[pos] == "]") begin pos++; return array_value; end
    forever begin
      array_value.array_value.push_back(parse_value());
      if (failed) return null;
      skip_ws();
      if (pos >= text.len()) begin fail("unterminated array"); return null; end
      if (text[pos] == ",") begin pos++; continue; end
      if (text[pos] == "]") begin pos++; return array_value; end
      fail("expected ',' or ']' in array");
      return null;
    end
  endfunction

  protected function string parse_string();
    string result;
    result = "";
    pos++; // opening quote
    while (pos < text.len()) begin
      byte c = text[pos++];
      if (c == "\"") return result;
      if (c == "\\") begin
        if (pos >= text.len()) begin fail("unterminated escape"); return ""; end
        c = text[pos++];
        case (c)
          "\"": result = {result, "\""};
          "\\": result = {result, "\\"};
          "/" : result = {result, "/"};
          "b" : result = {result, 8'h08};
          "f" : result = {result, 8'h0C};
          "n" : result = {result, 8'h0A};
          "r" : result = {result, 8'h0D};
          "t" : result = {result, 8'h09};
          "u" : begin
            // The generator emits UTF-8; keep a replacement marker for \u
            // escapes rather than pretending to decode code points.
            if (pos + 4 > text.len()) begin fail("short \\u escape"); return ""; end
            pos += 4;
            result = {result, "?"};
          end
          default: result = {result, c};
        endcase
      end
      else begin
        result = {result, c};
      end
    end
    fail("unterminated string");
    return "";
  endfunction

  protected function npu_player_json_value parse_number();
    int start;
    bit is_real;
    string token;
    start = pos;
    is_real = 0;
    if (pos < text.len() && (text[pos] == "-" || text[pos] == "+")) pos++;
    while (pos < text.len()) begin
      byte c = text[pos];
      if (c >= "0" && c <= "9") begin pos++; continue; end
      if (c == "." || c == "e" || c == "E" || c == "+" || c == "-") begin
        is_real = 1;
        pos++;
        continue;
      end
      break;
    end
    if (pos == start) begin
      fail("invalid number");
      return null;
    end
    token = text.substr(start, pos - 1);
    if (is_real) return npu_player_json_value::make_real(token.atoreal());
    return npu_player_json_value::make_int(token.atoi());
  endfunction
endclass

//=============================================================================
// npu_player_kv_parser - parse `key=value, key=value` from commands.tsv
//=============================================================================
class npu_player_kv_parser;
  static string last_error;

  static function npu_player_json_value parse(string body);
    npu_player_json_value object_value = npu_player_json_value::make_object();
    string parts[$];
    last_error = "";
    body = npu_player_text::trim(body);
    if (body == "") return object_value;
    // A whole-object body is either JSON (`{"..."}`) or IR-style (`{k:v}`).
    if (body[0] == "{" && body[body.len() - 1] == "}") begin
      npu_player_json_parser parser = new(body);
      npu_player_json_value parsed = parser.parse();
      if (parser.ok() && parsed != null && parsed.is_object()) return parsed;
      // Fall through: the braces may hold bare IR key/value pairs.
      body = body.substr(1, body.len() - 2);
    end
    npu_player_text::split_top(body, parts);
    foreach (parts[i]) begin
      string key, raw;
      if (!npu_player_text::split_assignment(parts[i], key, raw)) begin
        last_error = {"cannot parse field: ", parts[i]};
        return null;
      end
      object_value.put(key, parse_scalar(raw));
    end
    return object_value;
  endfunction

  static function npu_player_json_value parse_scalar(string raw);
    raw = npu_player_text::trim(raw);
    if (raw == "") return npu_player_json_value::make_string("");
    if (raw == "true")  return npu_player_json_value::make_bool(1);
    if (raw == "false") return npu_player_json_value::make_bool(0);
    if (raw == "null")  return npu_player_json_value::make_null();
    if (raw[0] == "\"" || raw[0] == "'") begin
      if (raw.len() >= 2 && raw[raw.len() - 1] == raw[0])
        return npu_player_json_value::make_string(raw.substr(1, raw.len() - 2));
      return npu_player_json_value::make_string(raw);
    end
    if (raw[0] == "{" || raw[0] == "[") begin
      npu_player_json_parser parser = new(raw);
      npu_player_json_value parsed = parser.parse();
      if (parser.ok() && parsed != null) return parsed;
      return npu_player_json_value::make_string(raw);
    end
    begin
      bit ok;
      longint unsigned number = npu_player_text::to_uint(raw, ok);
      if (ok) return npu_player_json_value::make_int(longint'(number));
    end
    return npu_player_json_value::make_string(raw);
  endfunction
endclass

`endif // NPU_PLAYER_VALUE_SVH
