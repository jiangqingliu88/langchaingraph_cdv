# execution assets — CSV 契约（VPlan）

执行资产不再是 `execution_model.yaml` / case-model YAML，而是 `data/*.csv`：

| 文件 | 内容 |
|---|---|
| `dimensions.csv` | 维度 × 字段（type/width/min/max/values/boundary/realization） |
| `assertions.csv` | SVA / 检查规则（expr / signals / tp_bindings） |
| `scoreboards.csv` | 独立参考模型比对（checks / evidence / rules） |
| `sub_objects.csv` | 功能子对象树 |
| `cross_matrix.csv` | 交叉覆盖（matrix_key + payload JSON） |
| `behavior.csv` | 行为域（状态/迁移/序列/时序，JSON 列） |
| `config_space.csv` | 配置空间（JSON 列） |
| `execution_meta.csv` | object / object_code / sampling / generation |

`vagent vplan execute` 从这些 CSV 在**内存**里组装运行期模型；不再生成
`inputs/**/runtime_model.yaml`。CSV 是 VPlan 的契约输入，
运行期结构是临时产物，run 结束即删。
