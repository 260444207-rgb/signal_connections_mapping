# 网络命名规则

基本格式：SCREAMING_SNAKE_CASE。

来源优先级：有效连线名称 > 用户规则指定名称 > 功能_源端_目标端 > source_port_TO_selected_pin。

差分信号必须保留 `_P/_N`。如果 selected_pin 为空，net_name 必须为空。
