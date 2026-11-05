#!/usr/bin/env bash
# source 之后把 RISC-V 工具链 bin 放进 PATH。
# 依赖 setup_toolchain.py 生成的 prefix.mk。
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_here/prefix.mk" ]; then
  _prefix="$(sed -n 's/^RISCV_PREFIX ?= //p' "$_here/prefix.mk")"
  if [ -n "$_prefix" ]; then
    export PATH="$(dirname "$_prefix"):$PATH"
  fi
fi
unset _here _prefix
