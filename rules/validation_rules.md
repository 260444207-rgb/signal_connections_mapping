# 校验规则

必须校验：每个 normalized_connection 都有 decision；不存在多余 line_id；line_id 不重复；selected_pin / selected_pins 如果非空，必须逐字存在于入参 pin_info.json 中当前 line_id 源端器件编码对应的 pin 列表；不得只校验“存在于任意器件 pin 列表”；confidence 合法；有 selected_pin 时必须有 net_name；无 selected_pin 时不得 High；差分信号成对；总线位号连续；final row 字段完整。

如果 pin_info.json 中没有当前源端器件编码对应的 pin 列表，该器件相关行应保持 unresolved，不得输出模型猜测的 pin 名。

错误等级：ERROR 必须修复；WARNING 可继续但需记录；PASS 通过。
