# 校验规则

必须校验：每个 normalized_connection 都有 decision；不存在多余 line_id；line_id 不重复；selected_pin / selected_pins 如果非空，必须逐字存在于入参 pin_info.json 中当前 line_id 源端器件编码对应的 pin 列表；不得只校验“存在于任意器件 pin 列表”；confidence 合法；无 selected_pin 时不得 High；差分信号成对；总线位号连续；final row 字段完整。pin decision 不包含网络命名字段，网络命名由独立 skill 处理。

如果单 pin连接的 `source_port` 已逐字存在于当前器件 pin_info，最终 `selected_pin` 必须等于该 `source_port`；改成另一个合法 pin 也属于二级映射错误，必须报 ERROR。

如果 pin_info.json 中没有当前源端器件编码对应的 pin 列表或列表为空，该器件相关行应保持 unresolved，不得输出模型猜测的 pin 名；不得把框图 port、连线名、规则文本或器件常识生成的字符串当作 pin。

同一个 source_sheet_name + source_part_id 表示同一个物理器件实例。该实例内同一个 selected_pin 被多个不同 line_id 复用时，必须能被相同源端口扇出到多个目标端口、相同连线名称、相同 base_connection、多端口别名或用户规则解释；否则 validation 至少输出 WARNING，提醒用户检查 pin 复用冲突。

错误等级：ERROR 必须修复；WARNING 可继续但需记录；PASS 通过。
