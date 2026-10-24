"""事务模板 —— 把**声明**变成**实例**。

    TxnSpec（"gemm 事务长什么样"）+ mask + 地址 + tag  →  Transaction（"这一次"）

配对的落点在这里
    每条事务的指令组是**一起造出来的**（`spec.ops` 一次性展开），调用方拿到的
    永远是完整的 `Transaction` —— 没有任何 API 能只造其中一条。
    于是"孤立的一条 `gemm_drv_xn`"在类型上就不可表达（见 `domain/transaction.py`）。

    模板这一层做的事因此不是"拼装"，而是**按注册表把每条指令的字段填对**：
    flags 来自 op 注册表（**不是这里写死的** —— 手填 funct7 是这个仓库明令禁止的），
    mask 由调用方给，operands 从地址分配来。

`binds/writes` 从哪来
    文档 §3.14.4 第 2 条：MPU/VPU 计算类 IR **必须携带 binds/writes**，
    且 `binds` 里每个 ref 必须能在 registry 里找到 name。
    这里按 `TxnSpec.effects` 推断方向（write/read/move…），
    把参与的对象名翻成 `$t.<name>` 引用。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..domain import (AllocError, IrInstruction, OpRegistry, OperandUnsupportedError,
                      Operands, Flags, Transaction, UnresolvedRefError,
                      TransactionRegistry, TxnSpec, build_transaction,
                      parse_operands)
from .allocator import AllocationPlan
from .sequencer import Draw

#: 效应里哪些含义是"读"，哪些是"写"。**只按这几个词判** ——
#: 猜得太宽会把不读的东西记成读，比对模块就会去等一个永远不会变的区域。
_READ_EFFECTS = frozenset({"read", "gather", "compute", "reduce", "move"})
_WRITE_EFFECTS = frozenset({"write", "compute", "move", "broadcast", "convert",
                            "set_global_mask", "update_config"})


def ref(name: str) -> str:
    """对象名 → IR 里的 ref 符号。`img` → `$t.img`。"""
    return f"$t.{name}"


def instantiate(spec: TxnSpec, *, registry: OpRegistry, mask: str = "",
                plan: Optional[AllocationPlan] = None,
                draw: Optional[Draw] = None, tag: str = "",
                extra_operands: Optional[Dict[str, Any]] = None) -> Transaction:
    """一条事务声明 → 一次事务实例。

    `mask` 是这一组指令的目标核集合。NICE 与 VNICE 在 IR 里**都写成显式 mask**
    （文档 §3.2.1 第 2 条：写法统一，编码器负责具体装配）—— 所以这里不区分，
    区分的是 op 注册表里的 `mask_semantics`，那是编码器的事。

    `plan` 给出地址分配；事务里引用的对象从它取地址与 ref。
    没有用到任何对象的事务（sync / mask 这类）传 None 即可。
    """
    binds, writes = _data_flow(spec, plan)
    roles = _role_index(plan) if plan is not None else {}
    instructions = [
        _instruction(op_name, registry, mask=mask, plan=plan, draw=draw,
                     extra_operands=extra_operands, roles=roles, mask_text=mask,
                     bindings=spec.operands.get(op_name, {}))
        for op_name in spec.ops
    ]

    transaction = build_transaction(
        txn_id=spec.id,
        op=spec.primary_op,
        instructions=instructions,
        registry=registry,
        registry_key=spec.id,
        cfg=spec.cfg or _cfg_from_ops(spec, registry),
        requires=spec.requires,
        hard=spec.hard,
        effects=spec.effects,
    )
    # 把两张 ref 表挂到每一条指令上 —— 比对模块按**事务**索引，
    # 但执行器只看得到平铺的指令流，所以两者都要有。
    if binds or writes:
        transaction = _attach_refs(transaction, binds, writes)
    return transaction.with_tag(tag) if tag else transaction


def _attach_refs(transaction: Transaction, binds: Sequence[str],
                 writes: Sequence[Dict[str, Any]]) -> Transaction:
    """把整个事务的 binds/writes 挂到它的**每条**指令上。

    为什么不只挂在 drv 那条：执行器拿到的是平铺的指令流，它不知道
    "这条 pre 属于哪个事务"。全挂一份，任何一条都能回答"我这一组动了哪些张量"，
    而 `Transaction.binds/writes` 会去重 —— 不会重复计数。
    """
    attached = tuple(
        IrInstruction(
            op=ins.op, tag=ins.tag, mask=ins.mask, flags=ins.flags,
            operands=ins.operands, src=dict(ins.src), dst=dict(ins.dst),
            src_addr=ins.src_addr, dst_addr=ins.dst_addr,
            binds=tuple(binds), writes=tuple(writes), cfg=ins.cfg,
            fault=ins.fault, extra=dict(ins.extra))
        for ins in transaction.instructions)
    return Transaction(
        id=transaction.id, op=transaction.op, instructions=attached,
        pre=transaction.pre, hard=transaction.hard, effects=transaction.effects,
        pairing=transaction.pairing, requires=transaction.requires,
        cfg=transaction.cfg, registry_key=transaction.registry_key)


def _data_flow(spec: TxnSpec,
               plan: Optional[AllocationPlan]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """`effects` + `roles` → (读的 ref, 写的 ref)。**只认分配过的对象**。

    为什么必须对着 `plan` 过滤
        效应里的 `target` 五花八门：`dram_to_lmem` 是**方向**、`nice` 是
        **寄存器名**、`spad` 是**区域名**、`gemm` 是**操作名**。
        只按"长得像标识符"收的话，会凭空造出 `$t.dram_to_lmem` 这种引用 ——
        而文档 §3.0 契约 2 明说：**`ref` 解析失败 = 生成期失败**，
        不允许静默越界。凭空造 ref 正好是它要挡的那件事。
        （这个 bug 真的出现过：第一版把 `$t.nice` / `$t.dram_to_lmem` 都收进来了。）

    计算类的 binds/writes 从哪来
        文档 §3.14.4 要求 MPU/VPU 计算类**必须**带 binds/writes，
        却没说生成器怎么知道哪个对象是权重 —— 那取决于 case，不取决于指令。
        所以由 DSL 的 `alloc[].role` 声明，`TxnSpec.roles` 引用它。
        角色对不上就报 `UnresolvedRefError` —— 那正是那条契约要的失败。
    """
    binds: List[str] = []
    writes: List[Dict[str, Any]] = []

    if plan is None:
        # **没有地址计划 = 调用方明确不要 ref。**
        # 这是个正当的模式（搭一个模板出来看结构、跑不涉及数据的用例），
        # 所以不解析角色、也不报"角色对不上" —— 那会把"我根本没打算放地址"
        # 误报成"角色声明错了"。真正的角色校验发生在有计划的时候。
        return binds, writes

    known = set(plan.names())
    roles = _role_index(plan)

    # (a) 效应里直接点名了一个**存在的对象**（罕见但合法）
    for effect in spec.effects:
        name = _loose_name(effect.target)
        if name is None or name not in known:
            continue
        _add_flow(effect, name, binds, writes)

    # (b) 事务声明了角色 —— 计算类走这条
    for role_name in spec.roles.get("binds", []):
        name = roles.get(role_name)
        if name is None:
            raise UnresolvedRefError(
                f"{spec.id} 要绑定角色 {role_name!r} 的对象，但 alloc 里没有",
                target=f"{spec.id}.binds.{role_name}",
                fix=f"给对应的 alloc 条目加 `role: {role_name}`；"
                    f"当前已有角色：{sorted(roles) or '（无）'}")
        if ref(name) not in binds:
            binds.append(ref(name))
    for role_name in spec.roles.get("writes", []):
        name = roles.get(role_name)
        if name is None:
            raise UnresolvedRefError(
                f"{spec.id} 要写角色 {role_name!r} 的对象，但 alloc 里没有",
                target=f"{spec.id}.writes.{role_name}",
                fix=f"给对应的 alloc 条目加 `role: {role_name}`")
        entry = {"ref": ref(name)}
        if entry not in writes:
            writes.append(entry)

    return binds, writes


def _role_index(plan: Optional[AllocationPlan]) -> Dict[str, str]:
    """角色 → 对象名。同一角色**只认第一个** —— 两个都叫 out 就没法选了。

    重复的角色不是错误（一个 case 可能有两份权重），但事务只能绑到一个上，
    所以取先声明的那个，并由 `test_templates` 钉住这个选择规则。
    """
    if plan is None:
        return {}
    index: Dict[str, str] = {}
    for allocation in plan.allocations:
        role = getattr(allocation, "role", "")
        if role:
            index.setdefault(role, allocation.name)
    return index


def _add_flow(effect, name: str, binds: List[str],
              writes: List[Dict[str, Any]]) -> None:
    if effect.kind in _READ_EFFECTS and ref(name) not in binds:
        binds.append(ref(name))
    if effect.kind in _WRITE_EFFECTS:
        entry: Dict[str, Any] = {"ref": ref(name)}
        if effect.span:
            entry["range"] = effect.span
        if entry not in writes:
            writes.append(entry)


def _loose_name(target: str) -> Optional[str]:
    """效应里的 `target` 长得像个**标识符**吗（只是形状判断，不保证存在）。

    真正是不是对象由 `_data_flow` 对着 `plan` 判 —— 这个函数只排除
    明显不是名字的（空、带空格、带路径分隔符）。
    """
    text = (target or "").strip()
    if not text or text.startswith("$"):
        return None
    if all(ch.isalnum() or ch in "_." for ch in text):
        return text
    return None


def _cfg_from_ops(spec: TxnSpec, registry: OpRegistry) -> str:
    """事务没写 cfg 时，从它的指令上取。

    op 注册表的 `cfg_required` 是按名字前缀推的（见 `build_registry._cfg_for`），
    所以这里取第一条有值的 —— 同一事务里的指令吃同一张 cfg 表。
    """
    if spec.cfg:
        return spec.cfg
    for op_name in spec.ops:
        target = registry.find(op_name)
        if target is not None and target.cfg_required:
            return target.cfg_required
    return ""


def _instruction(op_name: str, registry: OpRegistry, *, mask: str,
                 plan: Optional[AllocationPlan], draw: Optional[Draw],
                 extra_operands: Optional[Dict[str, Any]],
                 roles: Optional[Dict[str, str]] = None,
                 bindings: Optional[Dict[str, str]] = None,
                 mask_text: str = "") -> IrInstruction:
    """按注册表给一条指令填字段。

    **flags 来自注册表，不是这里写死的** —— 它是指令身份的一部分
    （同一 funct7 下靠它区分多条指令，见 `domain/opcode.py` 模块头）。
    模板里出现十六进制字面量会被 `test_layering` 的守卫抓出来。

    **操作数按编码表的语义填**（`_resolve_operands`）—— 不是"从地址计划里
    随便挑一个对象塞进 rs1val"。历史版本就是那么干的：34 条指令里 24 条
    声明了 xs2=1 却没有 rs2val，编出来的字会读 x0（=0）当第二个操作数，
    在仿真里表现为算错且不报错。
    """
    spec = registry.get(op_name)
    operands = Operands(**(extra_operands or {}))
    src: Dict[str, Any] = {}
    addr_bits: Dict[str, Any] = {}
    gaps: List[Dict[str, str]] = []

    if plan is not None:
        operands, addr_bits, src, gaps = _resolve_operands(
            op_name, spec, plan, roles or {}, operands, addr_bits, src,
            bindings=bindings or {}, mask_text=mask_text)

    # **不带下划线** —— `_` 打头的键会被 `IrInstruction.to_dict` 挡在 IR 之外
    # （那是给内部提示用的）。gap 必须落在 IR 里看得见：它是"这一槽没填出来"
    # 的唯一痕迹，藏起来就等于静默。
    extra = {"operand_gap": gaps} if gaps else {}
    return IrInstruction(
        op=op_name, mask=mask,
        flags=Flags.from_tuple(spec.flags) if spec.flags else Flags(),
        operands=operands, src=src, extra=extra, **addr_bits)


#: 填不了的形态 → 该去补哪一块。**报错要能指路**，否则只能靠猜。
_UNSUPPORTED_FIX = {
    "addr_part": "多段拼接地址（如 `base_addr[43:40]` + `base_addr_src[17:0]`）"
                 "要按 §3.12.2 T4 把同一个地址的两段摆到不同位置，本版本还没实现",
    "scalar": "标量操作数（§3.14.1：标量走指令字段）—— DSL 目前没有标量值的来源",
    "cfg": "cfg 复合字段需要 Cfg 表（§3.12.9 的 cfg.registry.json，尚未接入）",
    "special": "这种写法 domain/operands.py 认不出 —— 不要把不认识的当认识的处理",
}


def _mask_value(mask_text: str) -> int:
    """`group_mask_drv_xn` 的 rs1val = `{16b_reserved, core_mask}` —— 从事务的 mask 取。

    §3.2.1 第 2 条：NICE 的目标核集合走**全局 group_mask 寄存器**，这条指令
    就是去更新它。所以它的操作数不是"某个对象的地址"，而是 mask 本身。
    """
    if not mask_text:
        return 0
    text = str(mask_text).strip()
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text, 0)
    except ValueError:
        raise AllocError(f"mask 不是数字：{mask_text!r}", target="mask",
                         fix="mask 写成 `0x000F` 这种十六进制字面量") from None


def _resolve_operands(op_name: str, spec, plan: "AllocationPlan",
                      roles: Dict[str, str], operands: "Operands",
                      addr_bits: Dict[str, Any], src: Dict[str, Any], *,
                      bindings: Dict[str, str], mask_text: str):
    """按编码表的**操作数语义**填 rs1val / rs2val。

    三条路子，按优先级：
      1. **事务显式声明**（`TxnSpec.operands`）—— 最可靠，`orig` 这种
         推不出来的名字只能靠它
      2. **从编码表的地址名推**（仅 `addr` 类）—— `base_addr_in[17:0]`
         里的 `in` 就是一个 DSL 角色，能直接对上
      3. **`mask` 槽** —— 从事务的 mask 取值，不经对象

    填不了的槽：**省略**（不填一个编出来的值），把原因记进
    `IrInstruction.extra["_operand_gap"]`。编出来的值会读 x0=0，
    比"空着"危险得多；空着则编码器那步会响亮拦下。

    **真正属于配置错误的仍然抛** —— 声明了一个 alloc 里不存在的角色、
    对象没有地址分配，这些是使用者该改的，不是"本版本还没实现"。
    """
    os_specs = parse_operands(spec.fields)
    bound = plan.bindings
    resolved: Dict[str, Any] = {}
    gaps: List[Dict[str, str]] = []
    first_obj: Optional[str] = None
    first_addr: Optional[int] = None

    for slot in ("rs1val", "rs2val"):
        os_ = os_specs[slot]
        if os_.kind == "none":
            continue
        if os_.kind == "mask":
            resolved[slot] = f"0x{_mask_value(mask_text):X}"
            continue

        if not os_.fillable:
            gaps.append({"slot": slot, "kind": os_.kind,
                         "why": _UNSUPPORTED_FIX.get(os_.kind, "认不出的写法"),
                         "raw": os_.raw})
            continue

        # 声明优先；`addr` 类还允许从编码表的地址名推（名字恰好是 DSL 角色）
        role = bindings.get(slot)
        if role is None and os_.kind == "addr":
            role = os_.role
        if role is None:
            gaps.append({
                "slot": slot, "kind": "undeclared",
                "why": f"编码表要 `base_addr_{os_.name}[…]`，但事务没声明它绑哪个角色",
                "raw": os_.raw,
            })
            continue

        obj = roles.get(role)
        if obj is None:
            # 使用者声明了一个 alloc 里没有的角色 —— 配置错误，不是"没实现"
            raise UnresolvedRefError(
                f"{op_name} 的 {slot} 声明绑角色 {role!r}，但 alloc 里没有这个角色",
                target=f"{op_name}.{slot}",
                fix=f"给对应的 alloc 条目加 `role: {role}`；"
                    f"当前已有角色：{sorted(roles) or '（无）'}",
            )
        if obj not in bound:
            raise UnresolvedRefError(
                f"{op_name} 的 {slot} 指向 {obj!r}，但它没有地址分配",
                target=f"{op_name}.{slot}",
                fix="检查 alloc 的 pool 是否在 memmap 的可玩池里（§3.12.7）",
            )

        address = bound[obj]
        try:
            resolved[slot] = f"0x{os_.field(address):X}"
        except ValueError as exc:
            gaps.append({"slot": slot, "kind": "overflow",
                         "why": str(exc), "raw": os_.raw})
            continue
        if first_obj is None:
            first_obj, first_addr = obj, address

    merged = {"rs1val": operands.rs1val, "rs2val": operands.rs2val}
    merged.update(resolved)
    new_ops = Operands(**merged)

    # `src` / `src_addr` —— 第一个解析到的地址对象。执行器按它们找源；
    # 有了上面的规则，"第一个"是**确定的**（rs1val 优先），不再是随便挑一个。
    if first_obj is not None:
        addr_bits["src_addr"] = f"0x{first_addr:X}"
        src["ref"] = ref(first_obj)
    elif gaps:
        # 一个地址都解不出来时，保留旧行为会让 `src_addr` 变成"随便挑的"——
        # 那比没有更糟。宁可不给。
        pass

    return new_ops, addr_bits, src, gaps


def instantiate_all(specs: Sequence[TxnSpec], *, registry: OpRegistry,
                    mask: str = "", plan: Optional[AllocationPlan] = None,
                    draw: Optional[Draw] = None,
                    tag_prefix: str = "T") -> List[Transaction]:
    """一串事务一次性实例化 —— 自动编 tag。

    tag 是 IR 上的锚点（`wait_done` / `expect_rd` 都靠它引用），所以它必须
    **稳定且唯一**：这里用序号，`L<n>` 那个前缀是文档样例里的写法。
    """
    return [
        instantiate(spec, registry=registry, mask=mask, plan=plan, draw=draw,
                    tag=f"{tag_prefix}{index + 1:02d}")
        for index, spec in enumerate(specs)
    ]


def ref_set(plan: Optional[AllocationPlan]) -> set:
    """本 case 能解析的对象引用集合 —— 标注层用它核对 `binds`。

    文档 §3.14.4：`binds` 里每个 ref 必须能在 registry 里找到 name。
    "registry" 在这里就是分配计划 —— 它就是"这次有哪些对象"的唯一答案。
    """
    if plan is None:
        return set()
    return {ref(name) for name in plan.names()}
