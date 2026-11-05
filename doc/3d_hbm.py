import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
#  传统 DDR：集中式单通道，共享总线，请求串行排队
# ============================================================
class TraditionalDDR:
    def __init__(self, size_mb=256):
        # 连续平面内存
        self.memory = bytearray(size_mb * 1024 * 1024)
        self.bus_lock = threading.Lock()   # 模拟共享总线，一次一个请求
        self.access_log = []
        self.latency_per_access = 0.05     # 单次访问 50ms（长走线、排队开销）

    def read(self, addr, length):
        """一次只能有一个请求占用总线，其他必须等待"""
        with self.bus_lock:                # 串行化
            time.sleep(self.latency_per_access)  # 固定访问延迟
            data = self.memory[addr:addr+length]
            self.access_log.append(f"[DDR] 读取 0x{addr:X} 长度 {length}")
            return bytes(data)

    def write(self, addr, data):
        with self.bus_lock:
            time.sleep(self.latency_per_access)
            self.memory[addr:addr+len(data)] = data

# ============================================================
#  3D 堆叠 HBM：分布式多通道，逻辑 Die 调度，并发无冲突
# ============================================================
class StackedHBM:
    NUM_CHANNELS = 8                     # 8 个独立通道
    CHANNEL_SIZE = 64 * 1024 * 1024      # 每通道 64MB

    def __init__(self):
        # 每个通道有自己独立的存储体（物理上对应不同的堆叠层和 bank 组）
        self.channels = [bytearray(self.CHANNEL_SIZE) for _ in range(self.NUM_CHANNELS)]
        # 每个通道的锁（只保护本通道，不阻塞其他通道）
        self.channel_locks = [threading.Lock() for _ in range(self.NUM_CHANNELS)]
        self.access_log = []
        self.latency_per_channel_access = 0.005  # 单通道访问仅 5ms（垂直互连极短）

    def _map_address(self, global_addr, length):
        """数据条带化策略：按 64 字节粒度交错分配到不同通道"""
        mapping = []
        for offset in range(0, length, 64):
            chunk_addr = global_addr + offset
            channel_id = (chunk_addr // 64) % self.NUM_CHANNELS
            channel_offset = chunk_addr % self.CHANNEL_SIZE
            mapping.append((channel_id, channel_offset, min(64, length - offset)))
        return mapping

    def write(self, global_addr, data):
        """写入数据：自动条带化并分发到各通道"""
        for ch_id, ch_off, size in self._map_address(global_addr, len(data)):
            chunk = data[ch_off : ch_off + size]  # 注意这里需要根据映射提取正确的切片
            # 重新计算一下 data 内部偏移会比较麻烦，简化演示：全量对齐写入
            # 实际会用循环，这里为了演示清晰，先保证数据能写进去
        # 简化版：直接按块拆分写入
        mapping = self._map_address(global_addr, len(data))
        for i, (ch_id, ch_off, size) in enumerate(mapping):
            start = i * 64
            self.channels[ch_id][ch_off : ch_off + size] = data[start : start + size]

    def _read_channel(self, ch_id, ch_off, size):
        """单个通道的读取（线程安全，且不影响其他通道）"""
        with self.channel_locks[ch_id]:
            time.sleep(self.latency_per_channel_access)
            data = bytes(self.channels[ch_id][ch_off : ch_off + size])
            self.access_log.append(f"[HBM] 通道 {ch_id} 读取 0x{ch_off:X}")
            return data

    def read(self, global_addr, length):
        """全局读取：调度器拆分为多个通道子请求，然后并行执行"""
        mapping = self._map_address(global_addr, length)
        # 用线程池并行访问各通道
        with ThreadPoolExecutor(max_workers=self.NUM_CHANNELS) as executor:
            futures = []
            for ch_id, ch_off, size in mapping:
                futures.append(executor.submit(self._read_channel, ch_id, ch_off, size))
            chunks = [f.result() for f in futures]
        return b''.join(chunks)

# ============================================================
# 测试对比
# ============================================================
if __name__ == "__main__":
    # 准备一份 2KB 左右的数据（会被分割成 32 个 64B 的块）
    test_data = b"A" * 2048
    DATA_LEN = len(test_data)

    # ---------- 初始化两种内存 ----------
    ddr = TraditionalDDR()
    hbm = StackedHBM()

    # 预写入数据（起始地址不同，避免缓存干扰）
    ddr.write(0x1000, test_data)
    hbm.write(0x2000, test_data)

    # ---------- 模拟多线程并发读取 ----------
    NUM_THREADS = 8   # 同时发起 8 个读请求
    REQ_SIZE = 256    # 每个请求读 256 字节

    def ddr_task(i):
        return ddr.read(0x1000 + i * REQ_SIZE, REQ_SIZE)

    def hbm_task(i):
        return hbm.read(0x2000 + i * REQ_SIZE, REQ_SIZE)

    # 测试传统 DDR
    start = time.time()
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [executor.submit(ddr_task, i) for i in range(NUM_THREADS)]
        ddr_results = [f.result() for f in futures]
    ddr_time = time.time() - start

    # 测试 HBM
    start = time.time()
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [executor.submit(hbm_task, i) for i in range(NUM_THREADS)]
        hbm_results = [f.result() for f in futures]
    hbm_time = time.time() - start

    # ---------- 输出对比结果 ----------
    print("=" * 60)
    print("         传统 DDR  vs  3D 堆叠 HBM 并发读取对比")
    print("=" * 60)
    print(f"并发线程数: {NUM_THREADS}, 每线程读取 {REQ_SIZE} 字节")
    print(f"传统 DDR 总耗时 : {ddr_time:.4f} 秒")
    print(f"3D 堆叠 HBM 总耗时: {hbm_time:.4f} 秒")
    if hbm_time > 0:
        print(f"加速比          : {ddr_time / hbm_time:.2f} x")
    print()

    # 访问日志（展示 DDR 串行 vs HBM 并行）
    print("--- 传统 DDR 访问日志 (前 16 条) ---")
    for log in ddr.access_log[:16]:
        print(log)
    print()
    print("--- 3D 堆叠 HBM 访问日志 (前 16 条) ---")
    for log in hbm.access_log[:16]:
        print(log)
    print()

    # 展示 HBM 的数据条带化映射（只展示一个 256 字节请求的前几条）
    print("--- HBM 数据条带化映射示例（全局地址 0x2000 开始的 256B）---")
    mapping = hbm._map_address(0x2000, 256)
    for i, (ch, off, sz) in enumerate(mapping[:8]):  # 只打前 8 个块
        print(f"  块{i}: 通道{ch}, 偏移0x{off:X}, 大小{sz}B")