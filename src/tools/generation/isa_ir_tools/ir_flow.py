"""Fixed-value IR parser and tensor generation flow."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .core import BITS, TensorGenError, build_layout, generate_tensor
from .formats import byte_hex, memh
from .ir_cfg import CfgError, bind_cfg_fields, pack_cfg, module_spec
from .ir_isa import ISAError, instruction_table, project_action, vector_variant, validate_opcode
from .scalars import generate_scalar
from .isa_versions import normalize_revision, normalize_address_schema, address_schema, REVISION_CHOICES


TB_OPS = {"raw_cmd", "wait_cycles", "wait_done", "wait_event", "signal_event",
          "nop", "watchdog", "mem_init", "mem_scrub", "checkpoint",
          "expect_rd", "expect_write", "expect_region", "expect_intr",
          "expect_idle", "expect_perf", "perf_window", "csr_write", "csr_read",
          "set", "intr_ack", "peer_cfg", "dram_cfg", "batch_begin", "batch_end",
          "spawn_async", "reset", "pwr_ctl"}


def tb_operation(statement):
    match = re.match(r"([A-Za-z][A-Za-z0-9_]*)\b", statement)
    return match.group(1) if match and match.group(1) in TB_OPS else None


def tb_fields(statement, name, line):
    body = statement[len(name):].strip()
    if body.startswith('{') and body.endswith('}'):
        # Positional IB payloads (e.g. raw_cmd {0x...}) are opaque.
        if not any(char in body for char in ':='):
            return {}
        return value(body, line)
    if body.startswith('('):
        return _call(statement, line)[1]
    if '=' in body:
        return _call(name + ' (' + body + ')', line)[1]
    return {}


class IRFlowError(ValueError):
    def __init__(self, code: str, message: str, line: int | None = None):
        self.code = code
        self.line = line
        where = f" at line {line}" if line is not None else ""
        super().__init__(f'{code}{where}: {message}')


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_HEX = re.compile(r"^[+-]?0[xX][0-9a-fA-F]+$")
# Resolved seq.ir annotates generation with output metadata (file, stream
# version, materialized specials); only these keys feed regeneration.
_GENERATION_FIELDS = {"mode", "pattern", "seed", "quantize_rm", "overflow_policy",
                      "denormal_policy", "special_values", "values", "raw_bits", "fields"}


def _split_top(text: str, delimiter: str):
    result, start, depth, quote = [], 0, 0, None
    for i, char in enumerate(text):
        if char in "\"'" and (i == 0 or text[i - 1] != "\\"):
            quote = None if quote == char else char if quote is None else quote
        if quote:
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == delimiter and depth == 0:
            result.append(text[start:i].strip())
            start = i + 1
    result.append(text[start:].strip())
    if delimiter == ',' and len(result) > 1 and any(not part for part in result[:-1]):
        raise IRFlowError("SYNTAX_ERROR", "empty item between commas")
    return [item for item in result if item]


def _statements(text: str, *, include_original=False):
    """One lexer for all declarations/actions, with typed delimiter checks."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    result, buffer, stack = [], [], []
    quote, escaped, comment = None, False, False
    line, start_line, quote_line = 1, None, None
    start_offset = 0
    pairs = {'(': ')', '[': ']', '{': '}'}

    def finish():
        value = ''.join(buffer).strip()
        if value:
            if value.endswith(','):
                raise IRFlowError("SYNTAX_ERROR", 'unfinished statement after trailing comma', start_line)
            result.append((value, start_line, text[start_offset:i].strip())
                          if include_original else (value, start_line))
        buffer.clear()

    i = 0
    while i < len(text):
        char = text[i]
        if comment and char != '\n':
            i += 1
            continue
        if comment:
            comment = False
        if quote:
            if char in '\r\n':
                raise IRFlowError("SYNTAX_ERROR", 'quoted strings cannot cross physical lines', quote_line)
            buffer.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
        elif char == '/' and text[i:i+2] == '//':
            comment = True
            buffer.append(' ')
            i += 1
        elif char in "\"'":
            if start_line is None:
                start_offset, start_line = i, line
            quote, quote_line = char, line
            buffer.append(char)
        elif char in '([{':
            if start_line is None:
                start_offset, start_line = i, line
            stack.append((char, line))
            buffer.append(char)
        elif char in ')]}':
            if not stack or pairs[stack[-1][0]] != char:
                expected = pairs[stack[-1][0]] if stack else 'no closing delimiter'
                raise IRFlowError('SYNTAX_ERROR', f'unexpected {char}; expected {expected}', line)
            stack.pop()
            buffer.append(char)
        elif char in ';\n' and not stack:
            if char == '\n' and ''.join(buffer).rstrip().endswith(','):
                buffer.append('\n')
            else:
                finish()
                start_line = None
        else:
            if not char.isspace() and start_line is None:
                start_offset, start_line = i, line
            buffer.append(char)
        if char == '\n':
            line += 1
        i += 1
    if quote:
        raise IRFlowError('SYNTAX_ERROR', 'unclosed quoted string', quote_line)
    if stack:
        opening, opening_line = stack[-1]
        raise IRFlowError('SYNTAX_ERROR', f'unclosed {opening} opened on line {opening_line}', line)
    finish()
    return result


def value(text: str, line: int):
    text = text.strip()
    if not text:
        raise IRFlowError('SYNTAX_ERROR', 'missing value', line)
    if text.startswith('[') and text.endswith(']'):
        return [value(x, line) for x in _split_top(text[1:-1], ",")]
    if text.startswith('{') and text.endswith('}'):
        result = {}
        for item in _split_top(text[1:-1], ","):
            assignment = _split_top(item, '=')
            if len(assignment) == 1:
                assignment = _split_top(item, ':')
            if len(assignment) != 2:
                raise IRFlowError('SYNTAX_ERROR', "object field requires = or :", line)
            key, raw = assignment
            key = key.strip().strip('"\'')
            if not _IDENT.fullmatch(key):
                raise IRFlowError('SYNTAX_ERROR', f'invalid object field {key!r}', line)
            if key in result:
                raise IRFlowError("DUPLICATE_FIELD", key, line)
            result[key] = value(raw, line)
        return result
    if text.startswith('"') or text.startswith("'"):
        if not re.fullmatch(r'"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'', text, re.S):
            raise IRFlowError('SYNTAX_ERROR', 'unexpected text after quoted value', line)
        return text[1:-1]
    if _HEX.fullmatch(text):
        return int(text.replace(" ", ""), 16)
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    if re.fullmatch(r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?", text):
        return float(text)
    if text == "true": return True
    if text == "false": return False
    if text == "null": return None
    if not re.fullmatch(r'\$?[A-Za-z_][A-Za-z0-9_.]*', text):
        raise IRFlowError('SYNTAX_ERROR', f'invalid value {text!r}; check missing commas or extra text', line)
    return text


def _call(statement: str, line: int):
    # Two accepted forms: name(key=value, ...) and name key=value, ...
    match = re.match(r'([.#&]?[A-Za-z_][A-Za-z0-9_.-]*)\s*\((\s*.*\s*)\)$', statement, re.S)
    if not match:
        match = re.match(r'([.#&]?[A-Za-z_][A-Za-z0-9_.-]*)\s+(.*)$', statement, re.S)
    if not match:
        return None
    name, body = match.groups()
    fields = {}
    for item in _split_top(body, ","):
        if '=' not in item:
            raise IRFlowError('SYNTAX_ERROR', "call field requires key=value", line)
        key, raw = item.split('=', 1)
        key = key.strip()
        if not _IDENT.fullmatch(key):
            raise IRFlowError('SYNTAX_ERROR', f'invalid parameter name {key!r}', line)
        if key in fields:
            raise IRFlowError("DUPLICATE_FIELD", key, line)
        fields[key] = value(raw, line)
    return name.lstrip('#'), fields


def _literal(value, field=None):
    if type(value) is int and (field in {"bits", "rs1val", "rs2val", "vn_6b_grp_mask", "vn_group_mask", "base", "address", "base_byte", "offset_bytes", "offset", "value", "cfg_reg_addr"}
                               or (field and ("addr" in field or field.endswith("_address") or field.startswith('cfg_poly_an_buf16_')))):
        return f'0x{value:08x}' if value >= 0 else f'-0x{-value:x}'
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        list_item_field = field if field in {"rs1val", "rs2val", "rs1vals", "rs2vals"} else None
        return "[" + ", ".join(_literal(item, list_item_field) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key}:{_literal(item, key)}" for key, item in value.items()) + "}"
    if value is True: return "true"
    if value is False: return "false"
    if value is None: return "null"
    return str(value)


def _fields(value):
    return ", ".join(f"{key}={_literal(item, key)}" for key, item in value.items())


class FixedIRFlow:
    def __init__(self, source: str, path: str = "<source>", *, cfg_lint=True, isa_revision=None):
        self.source, self.path = source, path
        self.isa_revision = normalize_revision(isa_revision)
        self.address_schema = address_schema(self.isa_revision)
        # cfg_lint=False keeps the pair check for GLSU cfg/drv as a no-op so
        # software authors own cfg correctness; enable it when the flow itself
        # generates stimulus and cannot be trusted to remember cfg writes.
        self.cfg_lint = cfg_lint
        self.case = {"schema_version": "ir_fixed_v1", "case_seed": 0, "instruction_policy": "explicit",
                     "csr_clk_rst": False}
        self.profile = {}
        self.consts: dict[str, Any] = {}
        self.scalars: dict[str, dict[str, Any]] = {}
        # The current scalar symbol table is updated by repeated declarations.
        # Keep every version for source-order reconstruction and debug tracing.
        self.scalar_history: list[dict[str, Any]] = []
        self._scalar_references = []
        self.tensors: dict[str, dict[str, Any]] = {}
        self.views: dict[str, dict[str, Any]] = {}
        # `views` is the current symbol table. Keep declaration order too,
        # because a repeated .view name is a deliberate state update.
        self.view_history: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self._ir_events: list[dict[str, Any]] = []
        self._parse_order = 0

    def _name(self, name, table, line):
        if not isinstance(name, str) or not _IDENT.fullmatch(name):
            raise IRFlowError("INVALID_NAME", str(name), line)
        if (name in table or name in self.consts or name in self.scalars
                or (table is self.scalars and (name in self.tensors or name in self.views))):
            raise IRFlowError("DUPLICATE_SYMBOL", name, line)

    def _resolve(self, value, line, field=None):
        if isinstance(value, list):
            return [self._resolve(item, line, field) for item in value]
        if isinstance(value, dict):
            return {key: self._resolve(item, line, key) for key, item in value.items()}
        # Bare scalar names are accepted in numeric operand/cfg slot. Keep
        # names, view references and enum strings as symbols, not bit patterns.
        if (isinstance(value, str) and value in self.scalars
                and (field in ("rs1val", "rs2val", "scalar_in", "scalar_in1", "scalar_in2")
                     or (field is not None and field.startswith('cfg')))):
            scalar = self.scalars[value]
            ref = {'symbol': scalar['name'], 'dtype': scalar['dtype'],
                   'element bits': scalar['element_bits'], 'bits': scalar['bits'],
                   'version': scalar.get('version', 0),
                   'declaration line': scalar.get('source', {}).get('line'), 'field': field}
            if ref not in self._scalar_references:
                self._scalar_references.append(ref)
            return scalar['bits']
        if isinstance(value, str) and value.startswith("$"):
            key = value[1:]
            if key.startswith("const."):
                key = key[6:]
                if key not in self.consts:
                    raise IRFlowError("UNDEFINED_SYMBOL", value, line)
                return self.consts[key]
            if key in self.consts:
                return self.consts[key]
            if key.endswith('.bits') and key[:-5] in self.scalars:
                scalar = self.scalars[key[:-5]]
                ref = {'symbol': scalar['name'], 'dtype': scalar['dtype'],
                       'element bits': scalar['element_bits'], 'bits': scalar['bits'],
                       'version': scalar.get('version', 0),
                       'declaration line': scalar.get('source', {}).get('line'), 'field': field}
                if ref not in self._scalar_references:
                    self._scalar_references.append(ref)
                return scalar['bits']
            raise IRFlowError("UNDEFINED_SYMBOL", value + '; scalar references require $NAME.bits', line)
        return value

    def parse(self):
        for statement, line, original in _statements(self.source, include_original=True):
            self._parse_order += 1
            order = self._parse_order
            tb_op = tb_operation(statement)
            if tb_op:
                action = {"op": tb_op, "fields": tb_fields(statement, tb_op, line),
                          "passthrough": original,
                          "source": {"file": self.path, "line": line}}
                action["_view_snapshot"] = copy.deepcopy(self.views)
                action["_ir_order"] = order
                self.actions.append(action)
                self._ir_events.append({"kind": "action", "action": action, "order": order})
                continue
            statement = self._compact(statement, line)
            if statement.startswith("#const"):
                match = re.match(r"#const\s+([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.*)$", statement, re.S)
                if not match:
                    raise IRFlowError("SYNTAX_ERROR", "#const NAME = value required", line)
                name, raw = match.groups()
                self._name(name, {}, line)
                self.consts[name] = value(raw, line)
                continue
            if statement.startswith("#case") or statement.startswith("#profile"):
                call = _call(statement[1:], line)
                if call is None:
                    raise IRFlowError("SYNTAX_ERROR", "metadata call expected", line)
                name, fields = call
                fields = self._resolve(fields, line)
                if name == 'case':
                    unknown = set(fields) - {"seed", "instruction_policy", "csr_clk_rst"}
                    if unknown:
                        raise IRFlowError("UNKNOWN_FIELD", str(unknown), line)
                    if "csr_clk_rst" in fields:
                        if fields["csr_clk_rst"] not in (0, 1, True, False):
                            raise IRFlowError("INVALID_PARAMETER", "csr_clk_rst must be 0/1", line)
                        self.case["csr_clk_rst"] = bool(fields["csr_clk_rst"])
                    if "seed" in fields:
                        self.case["case_seed"] = fields["seed"]
                    self.case.update({k: v for k, v in fields.items() if k != "csr_clk_rst"})
                elif name == 'profile':
                    self._validate_profile_version(fields, line)
                    self.profile = fields
                else:
                    raise IRFlowError("UNKNOWN_OP", name, line)
                continue
            action_count = len(self.actions)
            call = _call(statement, line)
            if call is not None:
                if call[0] in {"scalar", "allocate_data", "reserve_view", "reserve_output", "reserve_transform_view", "view"}:
                    self._declaration(call[0], call[1], line)
                    symbol = call[1].get("name")
                    if call[0] == "scalar":
                        declaration = copy.deepcopy(self.scalars[symbol])
                    elif call[0] == "allocate_data":
                        declaration = copy.deepcopy(self.tensors[symbol])
                    else:
                        declaration = copy.deepcopy(self.view_history[-1])
                    self._ir_events.append({"kind": "declaration", "name": call[0],
                                            "symbol": symbol, "declaration": declaration,
                                            "order": order})
                else:
                    self._action(statement, line)
            else:
                self._action(statement, line)
            if len(self.actions) > action_count:
                self.actions[-1]["_ir_order"] = order
                self._ir_events.append({"kind": "action", "action": self.actions[-1], "order": order})
        return self

    def _compact(self, statement, line):
        """Lower line-oriented syntax without renaming instruction mnemonics."""
        if statement.startswith(".reserve_output"):
            body = statement[len(".reserve_output"):]
            parts = _split_top(body, ",")
            name = parts.pop(0)
            call = _call("_compact(" + ", ".join(parts) + ")", line)
            fields = call[1]
            if "name" in fields:
                raise IRFlowError("DUPLICATE_FIELD", "name", line)
            fields["name"] = name
            return "reserve_output(" + _fields(fields) + ")"
        if statement.startswith(".const"):
            return "#const " + statement[7:]
        if statement.startswith((".case", ".profile")):
            directive, body = statement.split(None, 1)
            return f"#{directive[1:]}({body})"
        if statement.startswith((".tensor", ".bind", ".view", ".scalar")):
            directive, body = statement.split(None, 1)
            parts = _split_top(body, ",")
            name = parts.pop(0)
            call = _call("_compact(" + ", ".join(parts) + ")", line)
            fields = call[1]
            if "name" in fields:
                raise IRFlowError("DUPLICATE_FIELD", "name", line)
            fields["name"] = name
            if directive == ".scalar":
                return "#scalar(" + _fields(fields) + ")"
            if directive == ".tensor":
                if "generate" in fields:
                    if "generation" in fields:
                        raise IRFlowError("DUPLICATE_FIELD", "use generation or generate, not both", line)
                    fields["generation"] = fields.pop("generate")
                fields.setdefault("layout", {"profile": "linear_atom32"})
                if "generation" not in fields:
                    pattern = fields.pop("pattern", {"kind": "zeros"})
                    if isinstance(pattern, str):
                        pattern = {"kind": pattern}
                    fields["generation"] = {"mode": fields.pop("mode", "numeric"), "pattern": pattern}
                    if "seed" in fields:
                        fields["generation"]["seed"] = fields.pop("seed")
                op = "allocate_data"
            elif directive == ".bind":
                fields.setdefault("layout", {"profile": "linear_atom32"})
                for key in ("stride_dim1", "stride_dim2"):
                    if key in fields:
                        if key in fields["layout"]:
                            raise IRFlowError("DUPLICATE_FIELD", key, line)
                        fields["layout"][key] = fields.pop(key)
                op = "reserve_view"
            else:
                axes = {k: fields.pop(k) for k in ("dim2", "dim1") if k in fields}
                if axes:
                    if "slice" in fields:
                        raise IRFlowError("DUPLICATE_FIELD", "slice", line)
                    fields["slice"] = axes
                op = "view"
            if op == "allocate_data":
                return "allocate_data(" + _fields(fields) + ")"
            if op == "reserve_view":
                placement = {key: fields.pop(key) for key in ("region", "base", "address", "place") if key in fields}
                fields["placement"] = placement
                return "reserve_view(" + _fields(fields) + ")"
            return "view(" + _fields(fields) + ")"
        if _call(statement, line) is None and not statement.startswith(("#", "&")):
            parts = statement.split(None, 1)
            if len(parts) == 2 and "=" in parts[1]:
                return parts[0] + "(" + parts[1] + ")"
        return statement

    def _placement(self, value, line):
        if not isinstance(value, dict) or ("base" not in value and "address" not in value):
            raise IRFlowError("PLACEMENT_REQUIRED", "fixed base or address required", line)
        if value.get("base") == "auto" or value.get("address") == "auto":
            raise IRFlowError("PLACEMENT_REQUIRED", "auto is random-flow only", line)
        if "base" in value and "address" in value:
            raise IRFlowError("INVALID_PARAMETER", "base and address are mutually exclusive", line)

    def _declaration(self, name, fields, line):
        fields = self._resolve(fields, line)
        if name == "scalar":
            scalar_name = fields.get("name")
            if not isinstance(scalar_name, str) or not _IDENT.fullmatch(scalar_name):
                raise IRFlowError("INVALID_NAME", str(scalar_name), line)
            # Unlike tensor/const/view symbols, a scalar is a source-order
            # value binding. Re-declaring it updates subsequent references;
            # actions already parsed retain the old encoded bits.
            if scalar_name in self.consts or scalar_name in self.tensors or scalar_name in self.views:
                raise IRFlowError("DUPLICATE_SYMBOL", scalar_name, line)
            try:
                scalar = generate_scalar(fields, self.case['case_seed'])
            except TensorGenError as exc:
                raise IRFlowError(exc.code, str(exc), line) from exc
            scalar["source"] = {"file": self.path, "line": line}
            scalar["version"] = sum(1 for item in self.scalar_history if item["name"] == scalar_name)
            self.scalars[scalar_name] = scalar
            self.scalar_history.append(copy.deepcopy(scalar))
            return
        if name == "allocate_data":
            required = {"name", "shape", "dtype", "generation", "layout"}
            missing = required - set(fields)
            if missing:
                raise IRFlowError("MISSING_FIELD", str(missing), line)
            self._name(fields["name"], self.tensors, line)
            if isinstance(fields.get("generation"), dict):
                fields["generation"] = {key: value for key, value in fields["generation"].items()
                                        if key in _GENERATION_FIELDS}
            if "placement" in fields:
                self._placement(fields["placement"], line)
            tensor = dict(fields)
            tensor["source"] = {"file": self.path, "line": line}
            self.tensors[fields["name"]] = tensor
            return
        if name in ("reserve_view", "reserve_output", "reserve_transform_view"):
            required = {"name", "layout", "placement"}
            if name == "reserve_view":
                required.add("tensor")
            missing = required - set(fields)
            if missing:
                raise IRFlowError("MISSING_FIELD", str(missing), line)
            self._name(fields["name"], self.views, line)
            self._placement(fields["placement"], line)
            if name == "reserve_view" and fields["tensor"] not in self.tensors:
                raise IRFlowError("UNDEFINED_SYMBOL", fields["tensor"], line)
            view = dict(fields)
            view["kind"] = name
            view["source"] = {"file": self.path, "line": line}
            self.views[fields["name"]] = view
            self.view_history.append(copy.deepcopy(view))
            return
        if name == "view":
            if "tensor" in fields and "parent" not in fields and "slice" not in fields and "transform" not in fields:
                # Resolved seq.ir emits allocation views as ``.view NAME, tensor=...``;
                # accept that form so a seq.ir can feed the flow again.
                required = {"name", "layout", "placement"}
                missing = required - set(fields)
                if missing:
                    raise IRFlowError("MISSING_FIELD", str(missing), line)
                self._name(fields["name"], self.views, line)
                self._placement(fields["placement"], line)
                if fields["tensor"] not in self.tensors and fields["tensor"] not in self.views:
                    raise IRFlowError("UNDEFINED_SYMBOL", fields["tensor"], line)
                view = dict(fields)
                view["kind"] = "reserve_view"
                view["source"] = {"file": self.path, "line": line}
                self.views[fields["name"]] = view
                self.view_history.append(copy.deepcopy(view))
                return
            required = {"name", "parent"}
            missing = required - set(fields)
            if missing:
                raise IRFlowError("MISSING_FIELD", str(missing), line)
            has_slice, has_transform = "slice" in fields, "transform" in fields
            if has_slice and has_transform:
                raise IRFlowError("INVALID_PARAMETER", "use chained views: slice and transform live on separate .view statements", line)
            if not has_slice and not has_transform:
                raise IRFlowError("MISSING_FIELD", "view requires slice or transform", line)
            if has_transform:
                if fields["transform"] != "transpose":
                    raise IRFlowError("UNSUPPORTED_TRANSFORM", fields["transform"], line)
                if "placement" not in fields:
                    raise IRFlowError("PLACEMENT_REQUIRED", "transform view declares a new data allocation and needs explicit placement", line)
                self._placement(fields["placement"], line)
                parent = fields["parent"]
                if parent not in self.views and parent not in self.tensors:
                    raise IRFlowError("UNDEFINED_SYMBOL", parent, line)
                if parent in self.views and self.views[parent].get("kind") == "slice":
                    raise IRFlowError("INVALID_PARAMETER", "transform applies to tensors/allocation views, not to dimension slices", line)
                view = {**{key: value for key, value in fields.items()},
                        "kind": "transform",
                        "layout": fields.get("layout", {}),
                        "source": {"file": self.path, "line": line}}
                self.views[fields["name"]] = view
                self.view_history.append(copy.deepcopy(view))
                self._context_for(fields["name"], line)
                return
            if fields["parent"] not in self.views and fields["parent"] not in self.tensors:
                raise IRFlowError("UNDEFINED_SYMBOL", fields["parent"], line)
            slice_spec = fields["slice"]
            if (not isinstance(slice_spec, dict) or not slice_spec or set(slice_spec) - {"dim2", "dim1"}
                    or any(type(i) is not int or i < 0 for i in slice_spec.values())):
                raise IRFlowError("UNSUPPORTED_SLICE", "slice supports nonnegative integer dim2/dim1 selections; dim0 column views require materialization", line)
            view = dict(fields)
            view["kind"] = "slice"
            view["source"] = {"file": self.path, "line": line}
            self.views[fields["name"]] = view
            self.view_history.append(copy.deepcopy(view))
            self._context_for(fields["name"], line)
            return
        raise IRFlowError("UNKNOWN_OP", name, line)

    def _action(self, statement, line):
        self._scalar_references = []
        if statement.startswith(("#", ".")):
            raise IRFlowError("UNKNOWN_OP", "unrecognized directive; use .tensor, .bind, .view or .reserve_output for declarations", line)
        call = _call(statement, line)
        if call is None:
            parts = statement.split(None, 1)
            name, fields = parts[0], ({"raw": parts[1]} if len(parts) == 2 else {})
        else:
            name, fields = call
            fields = self._resolve(fields, line)
        try:
            validate_opcode(name)
        except ISAError as exc:
            raise IRFlowError(exc.code, str(exc), line) from exc
        self._normalize_vector_operands(name, fields, line, self.isa_revision)
        # Mark explicit ISA operands at parse time so every supported opcode
        # follows the same preservation rule, including opcodes with no
        # tensor/cfg projection helper yet.
        if "rs1val" in fields or "rs2val" in fields:
            fields["explicit_operands"] = True
        action = {"op": name, "fields": fields, "source": {"file": self.path, "line": line}}
        # Projection is intentionally deferred until after parsing. Preserve
        # the view table at this statement so a later same-name .view update
        # cannot retroactively change an earlier recursive use.
        action["_view_snapshot"] = copy.deepcopy(self.views)
        if self._scalar_references:
            action['scalar_references'] = list(self._scalar_references)
        self.actions.append(action)

    @staticmethod
    def _vnice_metadata(core_ids, line):
        if (not isinstance(core_ids, list) or not 1 <= len(core_ids) <= 4
                or any(type(core) is not int or not 0 <= core < 16 for core in core_ids)
                or len(set(core_ids)) != len(core_ids)):
            raise IRFlowError("INVALID_CORE_IDS", "core_ids must be unique 4-bit physical core IDs", line)
        groups = {core // 4 for core in core_ids}
        if len(groups) != 1:
            raise IRFlowError("VNICE_GROUP_MISMATCH", "one VNICE instruction may select cores from one 4-core group only", line)
        group_id = next(iter(groups))
        lanes = [core % 4 for core in core_ids]
        lane_mask = sum(1 << lane for lane in lanes)
        return group_id, lanes, lane_mask, (group_id << 4) | lane_mask

    @staticmethod
    def _expand_vnice_lanes(core_ids, values):
        expanded = [0, 0, 0, 0]
        for core, value in zip(core_ids, values):
            expanded[core % 4] = value
        return expanded

    @staticmethod
    def _normalize_vector_operands(name, fields, line, isa_revision=None):
        """Normalize VNICE operands to ISA lane semantics.

        VN01 has one shared rs1 and a four-lane rs2; VN11 has four-lane rs1
        and rs2. Sparse input values are expanded to local lanes 0..3.
        """
        lowered = str(name).lower()
        is_vnice = vector_variant(name) is not None or lowered.endswith(("_vn01", "_vn11")) or str(fields.get("variant", "")).lower() in {"vnice", "vn01", "vn11"}
        aliases = (("rs1vals", "rs1val"), ("rs2vals", "rs2val"))
        vector_present = False
        for alias, canonical in aliases:
            if alias in fields:
                if canonical in fields:
                    raise IRFlowError("DUPLICATE_FIELD", f"use either {canonical} or {alias}", line)
                fields[canonical] = fields.pop(alias)
                vector_present = True
            if isinstance(fields.get(canonical), list):
                vector_present = True
        if not is_vnice and not vector_present:
            return
        if not is_vnice:
            raise IRFlowError("VECTOR_OPERAND_ON_NICE", "per-core operand lists require a VNICE (_vn01/_vn11) instruction; NICE targets come from group_mask_drv_xn", line)
        variant = vector_variant(name) or ("vn11" if str(fields.get("variant", "")).lower() == "vn11" else "vn01")
        rs1, rs2 = fields.get("rs1val"), fields.get("rs2val")
        spec = instruction_table(isa_revision).get(name)
        # Unary VNICE instructions still have a vector rs1 (read/reduction),
        # or a vector rs2 (die cluster rs2_pre vn). No dummy vector required.
        if spec and (spec.flags[1:] in ("10", "01")):
            enabled = "rs1val" if spec.flags[1] == "1" else "rs2val"
            value = fields.get(enabled)
            if isinstance(value, list):
                cores = fields.get("core_ids", list(range(len(value))))
                if len(cores) != len(value):
                    raise IRFlowError("INVALID_CORE_IDS", "core_ids must match supplied lane values", line)
                group, lanes, mask, mask6 = FixedIRFlow._vnice_metadata(cores, line)
                if enabled == "rs1val" and variant == "vn01":
                    raise IRFlowError("INVALID_VECTOR_OPERAND", "VN01 rs1val is shared scalar", line)
                if any(type(v) is not int or not 0 <= v < (1 << 32) for v in value):
                    raise IRFlowError("INVALID_VECTOR_OPERAND", "entries must be unsigned 32-bit values", line)
                fields[enabled] = FixedIRFlow._expand_vnice_lanes(cores, value)
                fields.update(core_ids=cores, vector_operands=True, vn_group_id=group,
                              vn_core_mask=mask, vn_6b_grp_mask=mask6, vn_operand_format=variant)
                return
            if not vector_present:
                return
        if variant == "vn11":
            if not isinstance(rs1, list) or not isinstance(rs2, list):
                if vector_present:
                    raise IRFlowError("INVALID_VECTOR_OPERAND", "VN11 rs1val and rs2val must each contain 1 to 4 values", line)
                return
            if len(rs1) != len(rs2):
                raise IRFlowError("VECTOR_OPERAND_LENGTH", "VN11 rs1val and rs2val must contain the same number of core values", line)
        else:
            if isinstance(rs1, list):
                raise IRFlowError("INVALID_VECTOR_OPERAND", "VN01 rs1val is one shared 32-bit value; only rs2val is a lane vector", line)
            if not isinstance(rs2, list):
                if vector_present:
                    raise IRFlowError("INVALID_VECTOR_OPERAND", "VN01 rs2val must contain 1 to 4 lane values", line)
                return
        values = rs1, rs2 if variant == "vn11" else rs2
        if any(not 1 <= len(value) <= 4 for value in values):
            raise IRFlowError("INVALID_VECTOR_OPERAND", "VNICE vector values must contain 1 to 4 unsigned 32-bit values", line)
        if any(any(type(item) is not int or not 0 <= item < (1 << 32) for item in value) for value in values):
            raise IRFlowError("INVALID_VECTOR_OPERAND", "VNICE vector entries must be unsigned 32-bit values", line)
        count = len(rs2)
        core_ids = fields.get("core_ids", list(range(count)))
        if len(core_ids) != count:
            raise IRFlowError("INVALID_CORE_IDS", "core_ids must match the number of supplied lane values", line)
        group_id, lanes, lane_mask, mask6 = FixedIRFlow._vnice_metadata(core_ids, line)
        fields['core_ids'] = core_ids
        fields['vector_operands'] = True
        fields['vn_group_id'] = group_id
        fields['vn_core_mask'] = lane_mask
        fields['vn_6b_grp_mask'] = mask6
        if variant == "vn11":
            rs1_lanes = FixedIRFlow._expand_vnice_lanes(core_ids, rs1)
            rs2_lanes = FixedIRFlow._expand_vnice_lanes(core_ids, rs2)
            fields['rs1val'], fields['rs2val'] = rs1_lanes, rs2_lanes
            fields['vector_operand_cores'] = {str(core): {'rs1val': r1, 'rs2val': r2}
                                              for core, r1, r2 in zip(core_ids, rs1, rs2)}
        else:
            fields['rs2val'] = FixedIRFlow._expand_vnice_lanes(core_ids, rs2)
            fields['vector_operand_cores'] = {str(core): {'rs1val': rs1, 'rs2val': value}
                                              for core, value in zip(core_ids, rs2)}
        fields['vn_operand_format'] = variant

    def _placement_of(self, ref, line):
        views = getattr(self, "_active_views", self.views)
        if ref in views:
            view = views[ref]
            if view.get("kind") == "slice":
                return self._context_for(ref, line)["placement"]
            return view.get("placement", {})
        if ref in self.tensors:
            return self.tensors[ref].get("placement", {})
        raise IRFlowError("UNDEFINED_SYMBOL", str(ref), line)

    def _context_for(self, ref, line):
        metadata = getattr(self, "_tensor_metadata", {})
        source_tensor = None
        views = getattr(self, "_active_views", self.views)
        if ref in views:
            view = views[ref]
            if view.get("kind") == "slice":
                context = dict(self._context_for(view["parent"], line))
                shape = list(context["shape"])
                offset = 0
                for axis, index in view["slice"].items():
                    dim = {"dim2": 0, "dim1": 1}[axis]
                    if index >= shape[dim]:
                        raise IRFlowError("SLICE_OUT_OF_BOUNDS", f"{axis} selection exceeds parent shape", line)
                    offset += 32 * index * context["layout"]["stride_" + axis]
                    shape[dim] = 1
                placement = dict(context["placement"])
                base = placement.get("base", placement.get("address"))
                if type(base) is not int:
                    raise IRFlowError("ADDRESS_REQUIRED", "slice parent needs numeric base", line)
                placement.pop("address", None)
                placement["base"] = base + offset
                context["shape"] = shape
                request = {k: context["layout"][k] for k in ("stride_dim1", "stride_dim2")}
                # A slice keeps the parent's packed representation, including
                # INT4 nibble ordering, only shape/base are projected.
                if context["layout"].get("int4_nibble_order") is not None:
                    request["int4_nibble_order"] = context["layout"]["int4_nibble_order"]
                context["layout"] = build_layout(shape, context["dtype"], request)
                context["placement"] = placement
                context["ref"] = ref
                context["view_mapping"] = {"kind": "slice", "parent": view["parent"], "selection": view["slice"], "offset_bytes": offset}
                view["base_byte"] = base + offset  # output cache only; never used for resolution
                return context
            if view.get("kind") == "transform":
                parent = self._context_for(view["parent"], line)
                shape = [parent["shape"][0], parent["shape"][2], parent["shape"][1]]
                try:
                    layout = build_layout(shape, parent["dtype"], view.get("layout", {}))
                except TensorGenError as exc:
                    raise IRFlowError("INVALID_LAYOUT", str(exc), line) from exc
                return {"parent": ref, "ref": ref, "shape": shape, "layout": layout,
                        "placement": view["placement"], "metadata_origin": "transform_plan",
                        "view_mapping": {"kind": "transpose", "parent": view["parent"],
                                         "axes": [0, 2, 1], "index_rule": "dst[i,j,n] = src[b,n,j]"}}
            source_tensor = view.get("tensor")
            # The parent may be a tensor or another declaration view (for
            # example a reserve_output allocation view).
            parent_view = self.views.get(source_tensor, {})
            tensor = {**parent_view, **self.tensors.get(source_tensor, {}), **metadata.get(source_tensor, {})}
            spec = {**tensor, **view}
            request = {**parent_view.get("layout", {}),
                       **self.tensors.get(source_tensor, {}).get("layout", {}),
                       **view.get("layout", {})}
        elif ref in self.tensors:
            source_tensor = ref
            spec = {**self.tensors[ref], **metadata.get(ref, {})}
            request = self.tensors[ref].get("layout", {})
        else:
            raise IRFlowError("UNDEFINED_SYMBOL", str(ref), line)
        shape, dtype = spec.get("shape"), spec.get("dtype")
        if dtype in ("fp8", "fp4"):
            dtype = dtype + "_" + str(spec.get(dtype + "_format"))
        if (not isinstance(shape, list) or not 1 <= len(shape) <= 3
                or any(type(n) is not int or n <= 0 for n in shape) or dtype not in BITS):
            raise IRFlowError("CFG_CONTEXT_REQUIRED", f"{ref} needs supported dtype and positive shape", line)
        shape = [1] * (3 - len(shape)) + shape
        try:
            if source_tensor in metadata and not request:
                layout = metadata[source_tensor]["layout"]
            else:
                layout = build_layout(shape, dtype, request)
        except TensorGenError as exc:
            raise IRFlowError("INVALID_LAYOUT", str(exc), line) from exc
        source_metadata = metadata.get(source_tensor, {})
        return {"ref": ref, "source_tensor": source_tensor,
                "metadata_origin": "generated tensor" if source_metadata else "declaration",
                "tensor content digest": source_metadata.get("content_digest"),
                "tensor layout digest": source_metadata.get("layout_digest"),
                "shape": shape, "dtype": dtype, "layout": layout,
                "placement": self._placement_of(ref, line)}

    def _validate_profile_version(self, profile, line=None):
        try:
            declared = normalize_revision(profile.get('isa_revision', self.isa_revision))
        except ValueError as exc:
            raise IRFlowError("UNSUPPORTED_ISA_REVISION", str(exc), line) from exc
        if declared != self.isa_revision:
            raise IRFlowError("ISA_REVISION_MISMATCH", "source profile and selected ISA revision differ", line)
        if normalize_address_schema(profile.get('address_schema', self.address_schema)) != self.address_schema:
            raise IRFlowError("ADDRESS_SCHEMA_MISMATCH", "source profile and selected address contract differ", line)

    def _project_operands(self):
        """Project cfg and operands using the explicitly selected ISA contract."""
        self._validate_profile_version(self.profile)
        address_ops = {"tld_drv_xn", "ttld_drv_xn", "tst_drv_xn"}
        word_read_ops = {"rd_lemem_drv_xn"}
        word_write_ops = {"wr_lemem_drv_xn"}
        # Cfg shadow state: key is (src_ref, dst_ref); the record carries the
        # configuring module, group/operation, and covered cores.
        # Mirrors hardware semantics: a cfg write programs the module's config
        # registers for the group-masked cores; every later driver on those
        # cores uses that state until the next cfg rewrites it. One cfg may
        # legitimately serve many recursive drivers.
        self._cfg_shadow = {}
        self._pre_state = {}
        self._active_nice_cores = frozenset(range(16))
        for action in self.actions:
            self._active_views = action.get("_view_snapshot", self.views)
            fields = action["fields"]
            line = action["source"]["line"]
            if "passthrough" in action:
                continue
            if action["op"] == "group_mask_drv_xn":
                self._active_nice_cores = self._group_mask_cores(fields, line)
            if action["op"] in word_read_ops | word_write_ops and not {"rs1val", "rs2val"} <= set(fields) and ("src" in fields or "dst" in fields):
                self._project_lemem_word(action, line, write=action["op"] in word_write_ops)
            if action["op"] != "npu_cfg_drv_xn":
                try:
                    project_action(self, action, self._active_nice_cores, self._pre_state)
                except ISAError as exc:
                    raise IRFlowError(exc.code, str(exc), line) from exc
                # Projection uses the PDF instruction family, never a generic
                # # gemm shift applied to both local and global opcodes.
                if action["op"] in address_ops and "src" in fields and "dst" in fields:
                    self._check_cfg_shadow(action, "tst" if action["op"].startswith("tst_") else "glsu", fields["src"], fields["dst"],
                                           self._active_nice_cores, line)
                continue
            if action["op"] == "npu_cfg_drv_xn":
                module = fields.get("module", "")
                explicit_operands = "rs1val" in fields or "rs2val" in fields
                explicit_pair = {"rs1val", "rs2val"} <= set(fields)
                derived, controls = {}, {}
                binding = fields.get("bind")
                try:
                    if not explicit_pair and action.get('scalar_references'):
                        _, cfg_layout = module_spec(module)
                        for reference in action['scalar_references']:
                            target = reference['field']
                            if target in cfg_layout and reference['element bits'] > cfg_layout[target][3]:
                                raise CfgError("SCALAR_WIDTH_MISMATCH",
                                               f"{reference['symbol']} ({reference['element bits']} bits) does not fit "
                                               f"{target} ({cfg_layout[target][3]} bits); use explicit raw halfwords for split coefficients")
                    if binding is not None and not explicit_pair:
                        if not isinstance(binding, dict) or not binding:
                            raise IRFlowError("INVALID_CFG_BIND", "bind requires a nonempty role-to-symbol object", line)
                        contexts = {role: self._context_for(ref, line) for role, ref in binding.items()}
                        if str(module).lower().removesuffix(".cfg") in ("mpu", "vpu"):
                            outputs = {r: c for r, c in contexts.items() if r == "out"}
                            for output in outputs.values():
                                for role, input_ctx in contexts.items():
                                    if role in ("out", "orig"):
                                        continue
                                    if self._overlap(input_ctx, output):
                                        raise IRFlowError("UNSUPPORTED_INPLACE_BIND", f"{role}/{input_ctx['ref']} overlaps output/{output['ref']}; in-place operation needs an operation-specific rule", line)
                        derived, controls, origins = bind_cfg_fields(module, contexts, fields.get("operation"))
                        fields["cfg_binding_contexts"] = contexts
                        fields["cfg_derived_fields"] = derived
                        fields["cfg_field_sources"] = origins
                    # A complete explicit pair is already encoded ISA data.
                    # Keep it byte-for-byte and avoid requiring a complete cfg row.
                    packs = [] if explicit_pair else pack_cfg(module, fields.get("with", {}), derived, controls)
                    if packs and isinstance(binding, dict) and set(binding) == {"src", "dst"}:
                        group = packs[0]["cfg_group"]
                        operation = fields.get("operation") or {0: "tld", 1: "tst", 2: "tmov"}.get(group)
                        self._cfg_shadow[(binding["src"], binding["dst"])] = {
                            "module": str(module).lower(), "group": group, "operation": operation,
                            "cores": self._active_nice_cores, "line": line}
                except CfgError as exc:
                    raise IRFlowError(exc.code, str(exc), line) from exc
                fields["cfg_packs"] = packs
                if len(packs) == 1:
                    if "rs1val" not in fields:
                        fields["rs1val"] = packs[0]["rs1val"]
                    if "rs2val" not in fields:
                        fields["rs2val"] = packs[0]["rs2val"]
                fields["operand_encoding"] = ("explicit: rs1/rs2 preserved" if explicit_operands else
                                              "npu_cfg: rs1=group[7:0],row[7:0],payload[15:0]; rs2=payload[31:0]")
                fields["cfg_projection_status"] = "explicit_operands" if explicit_operands else "pdf_v02_complete_rows"
                if explicit_operands:
                    fields["explicit_operands"] = True

    def _group_mask_cores(self, fields, line):
        if "rs1val" in fields:
            value = fields["rs1val"]
            if type(value) is not int or not 0 <= value < (1 << 32):
                raise IRFlowError("INVALID_OPERAND", "group_mask rs1val must be unsigned 32-bit", line)
            return frozenset(core for core in range(16) if value >> core & 1)
        if "core_ids" in fields:
            core_ids = fields["core_ids"]
            if (not isinstance(core_ids, list) or not core_ids
                    or any(type(core) is not int or not 0 <= core < 16 for core in core_ids)):
                raise IRFlowError("INVALID_CORE_IDS", "group_mask core_ids must be 4-bit physical core IDs", line)
            return frozenset(core_ids)
        if "mask" in fields:
            mask = fields["mask"]
            if type(mask) is not int or not 0 < mask < (1 << 16):
                raise IRFlowError("INVALID_GROUP_MASK", "group_mask must be a nonzero 16-bit core mask", line)
            return frozenset(core for core in range(16) if mask >> core & 1)
        raise IRFlowError("MISSING_FIELD", "group_mask_drv_xn requires core_ids or mask", line)

    def _check_cfg_shadow(self, action, module, src_ref, dst_ref, driver_cores, line):
        if not self.cfg_lint:
            return
        cfg = self._cfg_shadow.get((src_ref, dst_ref))
        if cfg is None:
            return  # no cfg yet in this flow: software may configure outside the flow
        if cfg["module"] != module:
            raise IRFlowError("CFG_DRIVER_MISMATCH",
                              f"{action['op']} needs a {module} cfg for {src_ref}->{dst_ref}, "
                              f"but the last cfg at line {cfg['line']} programmed module {cfg['module']!r}",
                              line)
        expected_group = 1 if action["op"].startswith("tst") else 0
        expected_op = re.match(r"(t\w+)", action["op"]).group(1)
        if (cfg["group"], cfg["operation"]) != (expected_group, expected_op):
            raise IRFlowError("CFG_DRIVER_MISMATCH",
                              f"{action['op']} on {src_ref}->{dst_ref} requires group {expected_group} "
                              f"operation {expected_op}, but cfg written at line {cfg['line']} "
                              f"configured group {cfg['group']} operation {cfg['operation']!r}", line)
        missing = driver_cores - cfg["cores"]
        if missing:
            raise IRFlowError("CFG_CORE_MISMATCH",
                              f"{action['op']} targets core(s) {sorted(missing)} not covered by the cfg "
                              f"written at line {cfg['line']} (covered {sorted(cfg['cores'])})", line)

    def _project_lemem_word(self, action, line, *, write):
        """Resolve one 32-bit LMEM access from a view symbol and byte offset.

        The symbol selects the view's base address. `offset` is deliberately
        a byte offset: a word access must remain meaningful when the view dtype
        changes (for example BF16 versus FP32), and callers can address padding
        explicitly. It is never scaled by the element size.
        """
        fields = action['fields']
        ref_key = "dst" if write else "src"
        if ref_key not in fields:
            raise IRFlowError("MISSING_FIELD", f"{action['op']} requires {ref_key}=<view>", line)
        ref = fields[ref_key]
        context = self._context_for(ref, line)
        placement = context['placement']
        region = placement.get("region", "")
        if not isinstance(region, str) or not region.startswith("lmem_"):
            raise IRFlowError("INVALID_REGION", f"{action['op']} requires an LMEM view, got {region!r}", line)
        base = placement.get("base", placement.get("address"))
        if type(base) is not int:
            raise IRFlowError("ADDRESS_REQUIRED", f"{ref} needs a numeric LMEM base", line)
        offset = fields.get("offset", 0)
        if type(offset) is not int or offset < 0:
            raise IRFlowError("INVALID_OFFSET", "offset must be a nonnegative byte integer", line)
        address = base + offset
        if address % 4:
            raise IRFlowError("MISALIGNED_ADDRESS", f"32-bit LMEM access address 0x{address:x} is not 4-byte aligned", line)
        if address & (1 << 17) or region.endswith("cimc"):
            raise IRFlowError("INVALID_REGION", "wr/rd lmem supports SPAD only, not CIMC", line)
        span = context["layout"].get("span_bytes")
        if type(span) is not int or offset + 4 > span:
            raise IRFlowError("ADDRESS_OUT_OF_VIEW", f"word at offset 0x{offset:x} exceeds {ref} allocation span ({span} bytes)", line)
        if not 0 <= address < (1 << 18) or address + 4 > (1 << 18):
            raise IRFlowError("ADDRESS_OUT_OF_RANGE", "LMEM word address must fit the 18-bit address field", line)
        explicit_rs1 = "rs1val" in fields
        explicit_rs2 = "rs2val" in fields
        if write:
            value = fields.get("value")
            if type(value) is not int or not 0 <= value < (1 << 32):
                raise IRFlowError("INVALID_VALUE", "wr_lmem_drv_xn value must be an unsigned 32-bit raw value", line)
            if not explicit_rs2:
                fields["rs2val"] = value
            fields["operand_encoding"] = ("explicit: rs1/rs2 preserved" if explicit_rs1 or explicit_rs2 else
                                          "lmem word: rs1=address(dst)+offset, rs2=value[31:0]")
        else:
            fields["operand_encoding"] = ("explicit: rs1/rs2 preserved" if explicit_rs1 or explicit_rs2 else
                                          "lmem word: rs1=address(src)+offset, rs2=0")
        if not explicit_rs1:
            fields["rs1val"] = address
        fields["address"] = address
        fields["offset"] = offset
        fields["_view_context"] = context
        if explicit_rs1 or explicit_rs2:
            fields["explicit_operands"] = True

    @staticmethod
    def _overlap(left, right):
        """Conservative allocation-span check; gaps are not reusable by default."""
        lp, rp = left["placement"], right["placement"]
        if not lp or not rp or lp.get("region") != rp.get("region") or lp.get("place", {}) != rp.get("place", {}):
            return False
        lb, rb = lp.get("base", lp.get("address")), rp.get("base", rp.get("address"))
        if type(lb) is not int or type(rb) is not int:
            return False
        return lb < rb + right["layout"]["span_bytes"] and rb < lb + left["layout"]["span_bytes"]

    def tensor_case(self):
        return {"schema_version": "tensor_spec_v1", "case_seed": self.case["case_seed"],
                "tensors": [{key: value for key, value in tensor.items()
                             if key in {"name", "shape", "dtype", "fp8_format", "fp4_format", "role", "generation", "layout"}}
                            for tensor in self.tensors.values()]}

    def _public_actions(self):
        """Return actions without parser-only view snapshots."""
        return [{key: value for key, value in action.items()
                 if key not in {"_view_snapshot", "_ir_order"}}
                for action in self.actions]

    def generate(self, out_dir: str | Path, formats=("bin", "hex", "memh"), *, debug_json=False, tensor_manifest=None):
        self._check_references()
        specs = [{key: value for key, value in tensor.items()
                  if key in {"name", "shape", "dtype", "fp8_format", "fp4_format", "role", "generation", "layout"}}
                 for tensor in self.tensors.values()]
        # Generate first: cfg projection and the manifest consume the same
        # normalized metadata, including dtype and atom32 layout. Refresh on
        # every build so changing tensor parameters cannot leave stale cfg.
        if tensor_manifest is None:
            results = [generate_tensor(spec, self.case["case_seed"]) for spec in specs]
        else:
            from .core import digest
            manifest_path = Path(tensor_manifest)
            external = json.loads(manifest_path.read_text(encoding="utf-8"))
            if external.get("source_revision", {}).get("spec_digest") != digest(self.tensor_case()):
                raise IRFlowError("STALE_TENSOR_MANIFEST", "manifest does not match current tensor declarations/seed")
            items = external.get("tensors", [])
            if [item.get("name") for item in items] != [spec["name"] for spec in specs]:
                raise IRFlowError("INVALID_MANIFEST", "tensor names/order differ")
            results = []
            for item in items:
                binary = next((p for p in item["payloads"] if p["format"] == "bin"), None)
                if binary is None:
                    raise IRFlowError("INVALID_MANIFEST", "binary payload required")
                data = (manifest_path.parent / binary["file"]).read_bytes()
                actual = hashlib.sha256(data).hexdigest()
                if actual != binary["sha256"] or len(data) != binary["bytes"]:
                    raise IRFlowError("PAYLOAD_DIGEST_MISMATCH", item["name"])
                results.append({**item, "payload": data})
        self._tensor_metadata = {result["name"]: {key: result[key] for key in
                                                  ("shape", "dtype", "layout", "content_digest", "layout_digest")}
                                 for result in results}
        self._project_operands()
        self._active_views = self.views
        resolved_views = [self._context_for(name, None) for name in self.views]
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        tensor_dir = out / "tensors"
        tensor_dir.mkdir(exist_ok=True)
        manifest = []
        generated = []
        for spec, result in zip(specs, results):
            data = result["payload"]
            files = []
            for fmt in formats:
                path = tensor_dir / f"{spec['name']}.{fmt}"
                if fmt == "bin":
                    path.write_bytes(data)
                else:
                    path.write_text(byte_hex(data) if fmt == "hex" else memh(data), encoding="utf-8", newline="\n")
                files.append({"file": f"tensors/{path.name}", "format": fmt,
                              "bytes": path.stat().st_size,
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            result.pop("payload", None)
            result.pop("values", None)
            result["payloads"] = files
            result["placement"] = self.tensors[spec["name"]].get("placement")
            generated.append(result)
            manifest.append({key: result[key] for key in
                             ("name", "shape", "dtype", "layout", "codec", "content_digest", "layout_digest")})
            manifest[-1]["payloads"] = files
        (tensor_dir / "manifest.json").write_text(json.dumps({"schema": "tensor_manifest_v2",
                                                              "tensors": manifest,
                                                              "views": resolved_views}, indent=2) + "\n", encoding="utf-8")
        from .mem_init import MemInitError, resolve_mem_init
        for action in self.actions:
            if action["op"] == "mem_init":
                try:
                    action['resolved_mem_init'] = resolve_mem_init(self, action['fields'], generated, action['source']['line'])
                except MemInitError as exc:
                    raise IRFlowError("MEM_INIT_ERROR", str(exc), action['source']['line']) from exc
        binding_report = [{"source": action["source"], "module": action["fields"].get("module"),
                           "operation": action["fields"].get("operation"),
                           "bind": action["fields"].get("bind", {}),
                           "contexts": action["fields"].get("cfg_binding_contexts", {}),
                           "derived": action["fields"].get("cfg_derived_fields", {}),
                           "field_sources": action["fields"].get("cfg_field_sources", {}),
                           "with": action["fields"].get("with", {}),
                           "cfg_packs": action["fields"]["cfg_packs"]}
                          for action in self.actions if "cfg_packs" in action["fields"]]
        (out / "cfg_bindings.json").write_text(json.dumps({"schema": "ir_cfg_bindings_v1",
                                                           "actions": binding_report}, indent=2) + "\n", encoding="utf-8")
        (out / 'scalars.json').write_text(json.dumps({'schema': 'ir_scalars_v2',
                                                      'scalars': list(self.scalars.values()),
                                                      'history': list(self.scalar_history)}, indent=2) + '\n', encoding='utf-8')
        public_actions = self._public_actions()
        catalog = {"schema": "ir_case_catalog_v1", "isa_revision": self.isa_revision, "address_schema": self.address_schema, "case": self.case, "profile": self.profile,
                   "scalars": list(self.scalars.values()),
                   "scalar_history": list(self.scalar_history),
                   "tensors": generated, "views": list(self.views.values()),
                   "view_history": list(self.view_history), "actions": public_actions}
        case_directive = {"seed": self.case["case_seed"], "instruction_policy": self.case["instruction_policy"]}
        if self.case.get("csr_clk_rst"):
            case_directive["csr_clk_rst"] = 1
        lines = ["// Operand-resolved IR; cfg writes are complete rows. cmddata encoding has not run.",
                 ".case " + _fields(case_directive),
                 ".profile " + _fields({**self.profile, 'isa_revision': self.isa_revision, 'address_schema': self.address_schema})]
        source_map = []
        action_indices = {id(action): index for index, action in enumerate(self.actions)}
        generated_by_name = {item["name"]: item for item in generated}
        for event in sorted(self._ir_events, key=lambda item: item["order"]):
            if event["kind"] == "declaration":
                declaration = event["declaration"]
                name = event["name"]
                symbol = event["symbol"]
                if name == "scalar":
                    lines.append("// scalar " + symbol + " : " + _fields({
                        'dtype': declaration['dtype'], 'bits': declaration['bits'],
                        'element_bits': declaration['element_bits'],
                        'version': declaration.get('version', 0),
                        'declaration_line': declaration.get('source', {}).get('line')}))
                elif name == "allocate_data":
                    tensor = generated_by_name[symbol]
                    fields = {key: tensor[key] for key in ("shape", "dtype", "generation", "layout", "placement")}
                    fields["file"] = f"tensors/{symbol}.bin"
                    lines.append(".tensor " + symbol + ", " + _fields(fields))
                elif declaration.get("kind") == "reserve_output":
                    lines.append(".reserve_output " + symbol + ", " + _fields({
                        k: v for k, v in declaration.items()
                        if k not in ("name", "kind", "source", "base_byte")}))
                else:
                    lines.append(".view " + symbol + ", " + _fields({
                        k: v for k, v in declaration.items()
                        if k not in ("name", "kind", "source", "base_byte")}))
                continue
            action = event["action"]
            logical_index = action_indices[id(action)]
            lines.append(f"// source line {action['source']['line']}")
            if action.get('scalar_references'):
                lines.append('// scalar references ' + ', '.join(
                    f"{ref['symbol']}.bits=0x{ref['bits']:0{(ref['element bits']+3)//4}x} ({ref['dtype']})"
                    for ref in action['scalar_references']))
            fields = action["fields"]
            if action.get("resolved_mem_init") is not None:
                lines.append("mem_init " + _fields(action["resolved_mem_init"]))
                source_map.append({**action["source"], 'logical_action_index': logical_index,
                                   'output_line': len(lines), 'op': action['op'],
                                   'operand_source': 'tensor manifest and view'})
                continue
            if "passthrough" in action:
                lines.append(action["passthrough"])
                source_map.append({**action["source"], 'logical_action_index': logical_index,
                                   'output_line': len(lines), 'op': action['op'],
                                   'operand_source': 'passthrough'})
                continue
            if fields.get("explicit_operands"):
                # Preserve hand-encoded operands. Derived context remains in
                # debug JSON, while seq.ir stays directly usable as ISA input.
                output_fields = {key: value for key, value in fields.items()
                                 if key not in {"cfg_packs", "cfg_binding_contexts", "cfg_derived_fields",
                                                "cfg_field_sources", "operand_encoding", "cfg_projection_status",
                                                "explicit_operands", "vector_operands", "vector_operand_cores",
                                                "gemm_address_parts", "required_die_cluster_rs2_pre",
                                                "address", "_view_context", "_pre_state_written",
                                                "_pre_state_observed", "address_requirements"}}
                if str(fields.get("operand_encoding", "")).startswith(self.isa_revision + ':'):
                    output_fields["operand_encoding"] = fields["operand_encoding"]
                lines.append(action["op"] + " " + _fields(output_fields))
                source_map.append({**action["source"], "logical_action_index": logical_index,
                                   "output_line": len(lines), "op": action["op"],
                                   "operand_source": "explicit"})
            elif "cfg_packs" in fields:
                for pack in fields["cfg_packs"]:
                    origins = fields.get("cfg_field_sources", {})
                    derived_names = set(fields.get("cfg_derived_fields", {}))
                    with_names = set(fields.get("with", {}))
                    annotations = []
                    for name, value in pack["fields"].items():
                        source = origins.get(name)
                        if source:
                            origin = f"bind:{source['role']}:{source['ref']}:{source['attribute']}"
                        elif name in with_names:
                            origin = "with"
                        elif name in derived_names:
                            origin = "derived"
                        else:
                            origin = "row"
                        annotations.append(f"{name}={value}<{origin}>")
                    lines.append("// cfg fields " + f"module={fields['module']} group={pack['cfg_group']} "
                                 f"row={pack['cfg_row']} " + " ".join(annotations))
                    lines.append(f"{action['op']} module={fields['module']}, cfg_reg_addr=0x{pack['cfg_reg_addr']:04x}, "
                                 f"rs1val=0x{pack['rs1val']:08x}, rs2val=0x{pack['rs2val']:08x}")
                    source_map.append({**action["source"], "logical_action_index": logical_index,
                                       "output_line": len(lines), "op": action["op"],
                                       "cfg_reg_addr": pack['cfg_reg_addr']})
            else:
                output_fields = {key: value for key, value in fields.items()
                                 if key not in {"explicit_operands", "_pre_state_written",
                                                "_pre_state_observed", "address_requirements"}}
                lines.append(action["op"] + " " + _fields(output_fields))
                source_map.append({**action["source"], "logical_action_index": logical_index,
                                   "output_line": len(lines), "op": action["op"]})
        # A verbatim TB statement may span several physical lines.
        physical_lines = []; physical_line = 1
        for item in lines:
            physical_lines.append(physical_line)
            physical_line += item.count('\n') + 1
        for mapping in source_map:
            mapping['output_line'] = physical_lines[mapping['output_line'] - 1]
        (out / "seq.ir").write_text("\n".join(lines) + "\n", encoding='utf-8')
        (out / "build_report.txt").write_text(
            f"status: semantic ir generated\ntensors: {len(specs)}\nactions: {len(self.actions)}\n"
            f"expanded actions: {len(source_map)}\n"
            f"isa revision: {self.isa_revision}\naddress schema: {self.address_schema}\n"
            "references: checked\noperand projection: local glsu xn and cfg\n"
            "cfg register projection: pdf v02 complete rows glsu tst tmu mpu vpu noc\nencoding: not run\n"
            "Address placement is retained; full memmap legality is not checked.\n", encoding='utf-8')
        if not debug_json:
            return out
        (out / "tensor_spec.json").write_text(json.dumps({"schema_version": "tensor_spec_v1",
                                                          "case_seed": self.case["case_seed"], "tensors": specs}, indent=2) + "\n", encoding="utf-8")
        (out / "case_catalog.json").write_text(json.dumps(catalog, indent=2, default=str) + "\n", encoding="utf-8")
        (out / "seq.ir.json").write_text(json.dumps(public_actions, indent=2, default=str) + "\n", encoding="utf-8")
        (out / "source_map.json").write_text(json.dumps(source_map, indent=2) + "\n", encoding="utf-8")
        (out / "generation_report.json").write_text(json.dumps({"status": "semantic_ir_generated",
                                                                "isa_revision": self.isa_revision, "address_schema": self.address_schema,
                                                                "tensor_count": len(specs), "scalar_count": len(self.scalars),
                                                                "scalar_declaration_count": len(self.scalar_history), "encoding": "not_run"}, indent=2) + "\n", encoding="utf-8")
        return out

    def _check_references(self):
        for action in self.actions:
            if "passthrough" in action:
                continue
            views = action.get("_view_snapshot", self.views)
            symbols = set(self.tensors) | set(views)
            fields = action["fields"]
            refs = [fields[k] for k in ("src", "dst", "ref") if k in fields]
            refs = [item for ref in refs for item in (ref if isinstance(ref, list) else [ref])]
            if isinstance(fields.get("bind"), dict):
                refs.extend(fields["bind"].values())
            # Already-resolved IR carries authoritative rs1/rs2 bits; a symbolic
            # src/dst whose declaration was elided is provenance, not an operand.
            resolved = "operand_encoding" in fields or ("rs1val" in fields and "rs2val" in fields)
            for ref in refs:
                if not isinstance(ref, str) or ref not in symbols:
                    if resolved:
                        continue
                    raise IRFlowError("UNDEFINED_SYMBOL", str(ref), action["source"]["line"])


def compile_source(source: str | Path, out_dir: str | Path, *, debug_json=False, cfg_lint=True, isa_revision=None):
    path = Path(source)
    flow = FixedIRFlow(path.read_text(encoding="utf-8"), str(path), cfg_lint=cfg_lint, isa_revision=isa_revision).parse()
    return flow.generate(out_dir, debug_json=debug_json)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ir_flow", description="Compile fixed-value IR and generate tensors.")
    parser.add_argument("source")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--debug-json", action="store_true", help="Also write verbose JSON debug artifacts.")
    parser.add_argument("--isa-revision", choices=REVISION_CHOICES,
                        help="ISA contract name; only TSA VERSION V1.4 exists (v0.3 XLSX review contract retired 2026-11-07)")
    parser.add_argument("--compile-target", choices=["standalone", "cluster"], help="Optionally compile seq.ir for hardware; cluster interface is pending.")
    parser.add_argument("--core-id", type=int, help="Standalone OUT core ID (0..15).")
    parser.add_argument("--cfg-lint", action="store_true", default=True,
                        help="Check GLSU cfg/driver pair consistency (default).")
    parser.add_argument("--no-cfg-lint", dest="cfg_lint", action="store_false",
                        help="Disable cfg/driver pair lint; software authors own cfg correctness.")
    args = parser.parse_args(argv)
    if args.compile_target and args.core_id is None:
        parser.error("--core-id is required with --compile-target")
    if args.compile_target == "cluster":
        parser.error("cluster instr dispatch format is not defined yet")
    if args.core_id is not None and not 0 <= args.core_id < 16:
        parser.error("--core-id must be 0..15")
    try:
        out = compile_source(args.source, args.out_dir, debug_json=args.debug_json, cfg_lint=args.cfg_lint, isa_revision=args.isa_revision)
        if args.compile_target:
            from .cmd_compile import CompileError, compile_seq
            try:
                compile_seq(out / "seq.ir", out / "cmd_sch", target=args.compile_target, core_id=args.core_id, isa_revision=args.isa_revision)
            except (CompileError, ISAError) as exc:
                parser.exit(2, f"{exc}\n")
        return 0
    except (IRFlowError, TensorGenError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
