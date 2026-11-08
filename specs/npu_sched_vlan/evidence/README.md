# evidence — 跨 run 证据索引

`index.json` 由 `vagent vplan link <project> <run>` 维护；每个 linked run 另存
`runs/<run_id>.json`。索引只记路径与 sha256，不复制 EDA 数据。

`vagent vplan gate <project>` 读取索引 + run 的 `tp_matrix.json` /
`regression_stages.json` / `sv/asset_registry.csv`：

- 契约映射的 TP 全部 HIT/OBSERVED/BACKDOOR_HIT；
- 分级回归 PASS；
- `sv/` 资产声明了该 C-*；

才可能把 `assume` 推进到 `active`。缺任何一条都保持 `assume`；`--apply` 也只改
满足条件的行，不会自动 exempt。
