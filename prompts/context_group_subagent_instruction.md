# Context Group Subagent 指令

这是 `script/build_model_resolution_tasks.py` 生成的 `CTX_xxx.prompt.md` 的说明性版本。真实任务执行时，以任务包中的 `CTX_xxx.json` 和同目录生成的 `CTX_xxx.prompt.md` 为准。

subagent 的核心语义方法见：

```text
prompts/semantic_mapping_resolver.md
```

## 输入任务包

```json
{
  "context_group": {},
  "link_family_summary": {},
  "line_ids": [],
  "normalized_connections": [],
  "candidate_mappings": [],
  "source_device_pins": {},
  "natural_language_rules": {
    "full_text": "",
    "link_level_rules": "",
    "device_level_rules": "",
    "general_signal_rules": ""
  },
  "needs_model_resolution": [],
  "required_output": {}
}
```

## 工作方式

```text
1. 只处理当前任务包列出的 line_id。
2. 先阅读 context_group.link_family_id、link_family_source、analysis_strategy。
3. 有显式链路级数据时，先理解链路族/链路实例，再分析单条连接。
4. 没有链路级数据时，按源/目的器件类型、源Block名称、源Port、connection_name 和 mapping_family 兜底分析。
5. 同类型不同实例可以共享 pin 功能理解，但每条 line_id 的实例编号、对端端口、网络名必须独立判断。
6. 信息不足时输出 unresolved，不得硬猜。
```

## 输出格式

只输出 JSON 数组：

```json
[
  {
    "line_id": "",
    "selected_pin": "",
    "selected_pins": [],
    "decision_type": "model_resolved|unresolved",
    "confidence": "High|Medium|Low",
    "analysis": "",
    "net_name": "",
    "net_names": [],
    "needs_human_review": false
  }
]
```

一条逻辑连接对应多个物理 pin 时，使用 `selected_pins`、`net_names`、`analyses`、`confidences` 数组；不要在模型输出里新增 `line_id`。
