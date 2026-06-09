# 校验规则

必须校验：每个 normalized_connection 都有 decision；不存在多余 line_id；line_id 不重复；selected_pin 如果非空，必须存在于 pins.json；confidence 合法；有 selected_pin 时必须有 net_name；无 selected_pin 时不得 High；差分信号成对；总线位号连续；final row 字段完整。

错误等级：ERROR 必须修复；WARNING 可继续但需记录；PASS 通过。
