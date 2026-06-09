# 运行时模板 Gate 规则

运行时模板应用前必须检查：group_id、source block 类型、target block 类型、source port pattern、target port pattern、pin candidate、方向、用户规则冲突、项目规则冲突、总线/差分位号。

全部必需项通过时，模板可应用；未通过时写入 needs_model_resolution.jsonl，并说明原因。
