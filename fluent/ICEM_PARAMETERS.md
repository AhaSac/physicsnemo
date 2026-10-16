# ICEM 窗口调用参数（开发中）

当前入口仍为 `run_meshing.py` 的 `icem_hex` 方案。只有与输入几何指纹一致的三维 blocking 模板才可运行。实际叶轮模板尚未完成，不能把下述接口当作任意叶轮自动分块已经成功。

配置 JSON 中可传入：

```json
{
  "icem_hex_templates": {"4impeller": "绝对路径/template.json"},
  "icem_hex_node_counts": {"streamwise": 81, "spanwise": 25},
  "icem_hex_edge_parameters": {
    "spanwise": {
      "start_spacing_mm": 0.04,
      "end_spacing_mm": 0.04,
      "start_growth": 1.2,
      "end_growth": 1.2,
      "max_spacing_mm": 8
    }
  }
}
```

边组名称由模板定义，上例名称仅示意。节点数包括两端节点，必须为整数且至少为 2。间距单位 mm、值大于 0；增长率至少为 1。未指定的分布值继承模板。首末方向严格对应模板中的有向顶点对；反向公共边的首末参数会交换，冲突会在启动 ICEM 前报错。

`template_evidence.json` 保存输入参数和模板指纹，`edge_parameters.tsv` 保存 ICEM 生成后的实际节点数、分布规律、长度、最大间距、首末间距和增长率。固定节点数可能使实际增长率与请求值不同，窗口应同时显示两者。

已在独立长方体夹具验证：x 向 7 节点、首末间距 2 mm、请求增长率 1.2、最大间距 8 mm，生成 96 个纯六面体；实际首末间距约 1.99976 mm，实际增长率约 2.3408。这不是叶轮网格质量验证。

尚未开放分布规律切换和光顺参数：需先完成原生命令实测及质量改善/回退验证。

窗口可读取 `icem_parameters.schema.json` 生成上述 ICEM 配置字段；这是配置片段的 schema，不是完整任务 schema。边组名称及几何绑定仍由运行时读取模板校验。

实际 4 号入口分区：SpaceClaim 分割与 Parasolid 导入已成功；ICEM 自动扫掠报 `Found free block in swept body`，仅得到二维面分块，三维检查拒绝执行。仍需建立适合该流道的三维 blocking 模板，才能验证上述参数对叶轮体网格的影响。
