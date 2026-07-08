# 网络命名规则

基本格式：`源block英文名_目的block英文名_源/目的port英文名`。

其中：

```text
1. 源block名和目的block名必须转换为英文简称。
2. 源/目的 port 只选择一个拼接到末尾。
3. port 选择优先级：
   a. 先看 port 是否有含义；有含义的优先选择。
   b. 如果源/目的 port 都有含义或都没有含义，则优先选择包含数字的 port。
   c. 如果仍无法区分，选择源 port。
4. block 和 port 中的中文必须翻译为英文或英文缩写。
5. 最终网络名使用 SCREAMING_SNAKE_CASE。
```

`LINE_xxx`、`line`、包含 `line` 的连线名称是画图工具默认连线名，不能直接覆盖网络名。当前规范不再优先使用连线名称，也不使用模型输出的 `net_name` 覆盖脚本生成结果。

差分信号必须保留 `_P/_N`。如果 selected_pin 为空，net_name/net_names 必须为空。
