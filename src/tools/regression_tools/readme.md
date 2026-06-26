
## 🚀 使用方法

### 1. 生成并执行（全流程）
```bash
# 生成目录并以 mock 模式执行（仅打印）
python regression_framework.py --config regression.yaml --action all --mode mock

# 生成目录并本地执行（真实运行）
python regression_framework.py --config regression.yaml --action all --mode local

# 生成目录并 LSF 提交
python regression_framework.py --config regression.yaml --action all --mode lsf
```

### 2. 仅生成（不执行）
```bash
python regression_framework.py --config regression.yaml --action generate --mode mock
```

### 3. 仅执行已有的目录
```bash
python regression_framework.py --action run --mode local --input-dir regression_local_20260626_120000
```

### 4. 只编译或只跑测试
```bash
python regression_framework.py --config regression.yaml --action all --mode local --build-only
python regression_framework.py --config regression.yaml --action all --mode local --test-only
```

### 5. LSF 自定义队列/资源
```bash
python regression_framework.py --config regression.yaml --action all --mode lsf --lsf-queue long --lsf-resource "rusage[mem=8192]"
```

---

## 🧩 设计模式应用说明

| 设计模式 | 应用位置 | 说明 |
| :--- | :--- | :--- |
| **策略模式** | `ExecutionStrategy` 及其子类 | 封装不同的执行行为（Mock/Local/LSF），可灵活切换 |
| **工厂模式** | `TaskFactory` | 创建 `BuildTask` 和 `TestTask` 对象，解耦创建逻辑 |
| **命令模式** | `Task` 及其子类 | 将每个构建/测试封装为命令，统一执行接口 |
| **构建器模式** | `ConfigBuilder` | 分步构建 `Config` 对象，处理复杂的加载、展开逻辑 |
| **外观模式** | `main()` 和框架整体 | 提供统一入口，隐藏内部复杂性 |

---

## 📦 依赖

- Python 3.6+
- `pyyaml`、`jinja2`（安装：`pip install pyyaml jinja2`）

---

## 📁 生成的目录结构（与之前一致）

```
regression_mock_20260626_120000/
├── build_build_simple/
│   ├── pre_build.sh
│   ├── build.sh
│   ├── post_build.sh
│   ├── test_test_smoke_seed_100/
│   │   ├── pre_sim.sh
│   │   ├── sim.sh
│   │   └── post_sim.sh
│   └── test_test_alu_..._seed_123/
│       └── ...
└── build_build_coverage/
    └── ...
```

现在你有了一个**可扩展、易维护**的统一框架，通过设计模式将各模块解耦，方便后续增加新功能（如并行调度、更精细的依赖控制等）。😊


# 从之前的回归目录提取失败用例，复制脚本到新目录
python regression_framework.py --rerun-failed regression_lsf_20260626_160000

# 可以指定输出目录
python regression_framework.py --rerun-failed regression_lsf_20260626_160000 --output-dir my_rerun

# 之后可以手动进入新目录执行
cd my_rerun
ls build_*/test_*/*.sh   # 查看复制的脚本
# 手动运行某个测试
cd build_build_base/test_test_alu_ADD_seed_1 && ./sim.sh

# 或者使用框架再次运行（假设目录结构完整）
python regression_framework.py --action run --mode local --input-dir my_rerun