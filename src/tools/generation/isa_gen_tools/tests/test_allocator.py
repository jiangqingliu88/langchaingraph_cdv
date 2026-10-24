"""memmap、可玩池、地址分配。

三条要害：
  · **伪空间不得用于分配**（`real_size` < `size`）
  · **分配无解就是编译期失败**，不回退到非对齐地址（§3.12.5）
  · **E5：加一个对象不动既有对象的地址**
"""
from __future__ import annotations

import pytest

from ..analysis import load_dsl
from ..compile import (AllocationPlan, Sequencer, allocate, build_play_space,
                       element_size, tensor_bytes)
from ..domain import AllocError, IsaGenError, LintError
from ..domain.memmap import Region, format_size, parse_size
from ..repository.memmap import load_memmap, memmap_from_dict

MEM = load_memmap()


def dsl(text: str):
    return load_dsl(text)


BASE = "meta: {name: t, seed: 7}\n"


def with_alloc(entries: str) -> str:
    return BASE + "alloc:\n" + entries


def plan_for(text: str) -> AllocationPlan:
    document = dsl(text)
    return allocate(document, build_play_space(document, MEM), MEM, seed=7)


class TestSizeParsing:
    @pytest.mark.parametrize("text,expected", [
        ("128KB", 131072), ("2GB", 2 * 1024 ** 3), ("512MB", 512 * 1024 ** 2),
        ("4KB", 4096), ("32", 32), (4096, 4096), ("1TB", 1024 ** 4),
    ])
    def test_human_sizes(self, text, expected):
        assert parse_size(text) == expected

    def test_unparseable_size_is_an_error(self):
        """`128kb` 写成 `128` 的话，分配器会把 128 字节当区域大小 ——
        安静地放不下任何东西。所以不认就报错，不猜。"""
        with pytest.raises(IsaGenError, match="看不懂的尺寸"):
            parse_size("一百二十八")

    def test_format_round_trip(self):
        assert format_size(131072) == "128KB"
        assert format_size(2 * 1024 ** 3) == "2GB"


class TestMemMap:
    def test_fixture_loads(self):
        assert MEM.region_names() == ["dram.common", "dram.share",
                                      "lmem.core.cimc", "lmem.core.spad"]

    def test_real_size_caps_allocatable(self):
        """Common DRAM 声明 512MB，真实只有 384MB —— 差的 128MB 是**伪映射**。

        把 `size` 当可分配范围，张量就会落进伪空间，而仿真里可能"看起来能跑"。
        """
        common = MEM.region("dram.common")
        assert common.size == 512 * 1024 ** 2
        assert common.allocatable_size == 384 * 1024 ** 2

    def test_reserved_is_data_not_prose(self):
        """负例要用保留区做越界，所以它得是**数据**。"""
        assert MEM.is_reserved(0x2_1800_0000)
        assert MEM.is_reserved(0x2_1FFF_FFFF)
        assert not MEM.is_reserved(0x2_17FF_FFFF)

    def test_overlaps_reserved_covers_the_span(self):
        # 从保留区前面开始、跨进去
        assert MEM.overlaps_reserved(0x2_17FF_F000, 0x2000)
        assert not MEM.overlaps_reserved(0x2_17FF_F000, 0x1000)
        assert not MEM.overlaps_reserved(0x2_2000_0000, 0x1000)

    def test_region_of_and_contains_span(self):
        spad = MEM.region("lmem.core.spad")
        assert spad.contains(0x1000) and not spad.contains(0x2_0000)

    def test_duplicate_region_name_is_rejected(self):
        with pytest.raises(IsaGenError, match="重复"):
            memmap_from_dict({"regions": [{"name": "a", "size": "1KB"},
                                          {"name": "a", "size": "1KB"}]})

    def test_empty_regions_is_rejected(self):
        """空 memmap 不是"宽松"，是"没得选" —— 分配器拿它一个合法地址都找不到。"""
        with pytest.raises(IsaGenError, match="没有任何 region"):
            memmap_from_dict({"regions": []})

    def test_unknown_region_lists_the_known_ones(self):
        with pytest.raises(IsaGenError) as info:
            MEM.region("dram.nope")
        assert "dram.share" in str(info.value)


class TestPlaySpace:
    def test_regions_are_the_whole_memmap_by_default(self):
        space = build_play_space(dsl(BASE), MEM)
        assert len(space.regions) == 4

    def test_exclude_removes_a_region(self):
        space = build_play_space(
            dsl(BASE + "resources: {exclude: [dram.common]}"), MEM)
        assert "dram.common" not in {r.name for r in space.regions}

    def test_excluding_everything_is_a_lint_error(self):
        """一条 `LintError`，不是"然后分配器找不到地方"那种二段式报错。"""
        text = BASE + "resources: {exclude: [%s]}" % ", ".join(MEM.region_names())
        with pytest.raises(LintError, match="一块可用 region 都不剩"):
            build_play_space(dsl(text), MEM)

    def test_unknown_exclude_names_the_offender(self):
        with pytest.raises(LintError) as info:
            build_play_space(dsl(BASE + "resources: {exclude: [nope]}"), MEM)
        assert info.value.target == "nope"

    def test_region_pool_declares_a_capacity(self):
        space = build_play_space(dsl(
            BASE + "resources:\n  region_pools:\n"
                   "    hot: {regions: [dram.share], size: 16MB}\n"), MEM)
        assert space.pool("hot").capacity == 16 * 1024 ** 2

    def test_pool_capacity_beyond_the_region_is_a_lint_error(self):
        with pytest.raises(LintError, match="超过"):
            build_play_space(dsl(
                BASE + "resources:\n  region_pools:\n"
                       "    hot: {regions: [lmem.core.spad], size: 1GB}\n"), MEM)

    def test_a_bare_region_name_works_as_a_pool(self):
        """`alloc: {pool: dram.share}` 是最常见的写法，不该要求先声明池。"""
        assert build_play_space(dsl(BASE), MEM).pool("dram.share").region.name \
            == "dram.share"

    def test_unknown_pool_lists_the_options(self):
        with pytest.raises(LintError) as info:
            build_play_space(dsl(BASE), MEM).pool("nope")
        assert "dram.share" in info.value.fix


class TestAllocation:
    def test_a_single_object_lands_at_offset_zero(self):
        plan = plan_for(with_alloc(
            "  - {name: img, pool: lmem.core.spad, shape: [1, 64, 256], dtype: fp16}\n"))
        (allocation,) = plan.allocations
        assert allocation.offset == 0
        assert allocation.size == 64 * 256 * 2

    def test_objects_do_not_overlap(self):
        plan = plan_for(with_alloc(
            "  - {name: a, pool: lmem.core.spad, shape: [64], dtype: fp32}\n"
            "  - {name: b, pool: lmem.core.spad, shape: [64], dtype: fp32}\n"))
        first, second = plan.allocations
        assert first.offset + first.size <= second.offset

    def test_addresses_bind_to_global(self):
        plan = plan_for(with_alloc(
            "  - {name: out, pool: dram.share, shape: [16], dtype: fp16}\n"))
        assert plan.bindings["out"] == MEM.region("dram.share").base

    def test_too_large_for_the_pool_is_an_alloc_error(self):
        """**无解就是无解** —— 文档明说分配器不回退到非对齐地址。"""
        with pytest.raises(AllocError, match="装不下"):
            plan_for(with_alloc(
                "  - {name: huge, pool: lmem.core.spad, shape: [1, 8192, 1024],"
                " dtype: fp32}\n"))

    def test_running_out_of_room_is_an_alloc_error(self):
        entries = "".join(
            f"  - {{name: t{i}, pool: lmem.core.spad, shape: [16384], dtype: fp32}}\n"
            for i in range(4))          # 4 × 64KB > 128KB
        with pytest.raises(AllocError, match="找不到位置"):
            plan_for(with_alloc(entries))

    def test_unknown_dtype_is_an_alloc_error(self):
        with pytest.raises(AllocError, match="dtype"):
            plan_for(with_alloc(
                "  - {name: x, pool: lmem.core.spad, shape: [8], dtype: fp64}\n"))

    def test_duplicate_object_names_are_rejected(self):
        """对象名是 `ref` 的锚点，重名会让 binds/writes 指错地方。"""
        with pytest.raises(AllocError, match="两个都叫"):
            plan_for(with_alloc(
                "  - {name: x, pool: lmem.core.spad, shape: [8], dtype: fp16}\n"
                "  - {name: x, pool: lmem.core.spad, shape: [8], dtype: fp16}\n"))

    def test_empty_alloc_is_fine(self):
        assert len(plan_for(BASE)) == 0


class TestDeterminism:
    def test_same_input_same_plan(self):
        text = with_alloc(
            "  - {name: a, pool: dram.share, shape: [64], dtype: fp32}\n"
            "  - {name: b, pool: dram.share, shape: [64], dtype: fp32}\n")
        assert plan_for(text).to_dict() == plan_for(text).to_dict()

    def test_addresses_are_order_dependent_and_that_is_stated(self):
        """**地址是"按声明顺序 bump"，所以插一个对象会挪动后面的。**

        这**不是** E5 的违例 —— E5（§3.12.9）说的是"新增张量不得改变既有张量的
        **比特值**"，那是 tensor 数据的事（`tensor_gen` 的职责），不是地址的事。

        把它写成测试而不是留个印象：**改动摆放策略时先看这里**。
        真要做到"插对象不挪地址"，得按 `hash(name)` 落点（会引入碰撞），
        或者做二次稳定性排序 —— 两条都是独立的设计决策，不顺手做。
        """
        before = plan_for(with_alloc(
            "  - {name: a, pool: dram.share, shape: [64], dtype: fp32}\n"))
        after = plan_for(with_alloc(
            "  - {name: z, pool: dram.share, shape: [64], dtype: fp32}\n"
            "  - {name: a, pool: dram.share, shape: [64], dtype: fp32}\n"))
        assert before.get("a").offset == 0
        assert after.get("a").offset == 64 * 4        # 被 z 顶到了后面

    def test_per_object_streams_are_independent(self):
        """**E5 的机制在这里**：每个对象一条独立的流。

        取数取多少次只影响**自己**那条 —— 所以"新增一个张量"不会挪动既有
        张量的取值。共用一个 RNG 的做法正是死在这一条上。
        """
        seq = Sequencer(7)
        first, second = seq.draw("a"), seq.draw("b")
        for _ in range(5):
            first.choice([1, 2, 3])
        assert second.choice([1, 2, 3]) == Sequencer(7).draw("b").choice([1, 2, 3])

    def test_sequencer_issues_one_stream_per_name(self):
        seq = Sequencer(7)
        assert seq.draw("tensor:img").seed == derive_ok(7, "tensor:img")
        assert seq.issued == ["tensor:img"]

    def test_draw_records_how_many_times_it_was_used(self):
        draw = Sequencer(1).draw("x")
        draw.choice([1]); draw.integer(0, 1)
        assert draw.draws == 2

    def test_weighted_falls_back_to_uniform_on_zero_weights(self):
        """权重全零时退化成均匀，而不是崩 —— 一份写错的权重不该让编译停摆。"""
        draw = Sequencer(3).draw("w")
        assert draw.weighted({"a": 0, "b": 0}) in {"a", "b"}


def derive_ok(case_seed: int, name: str) -> int:
    from ..domain.dsl import derive_seed
    return derive_seed(case_seed, name)


class TestHelpers:
    def test_element_sizes(self):
        assert element_size("fp16") == 2 and element_size("FP32") == 4

    def test_tensor_bytes_multiplies_the_shape(self):
        assert tensor_bytes([2, 3, 4], "fp16") == 48

    def test_empty_shape_is_one_element(self):
        assert tensor_bytes([], "fp32") == 4

    def test_non_positive_dimension_is_rejected(self):
        with pytest.raises(AllocError, match="非正"):
            tensor_bytes([0, 4], "fp16")
