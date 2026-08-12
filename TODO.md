[ ] 优化界面设计和元素
[ ] 发布到 PyPI（`pipx install interproof`）
[ ] Make a vscode plugin?
[ ] Better UI design (intractable buttons, etc.)
[ ] Call graph

[x] 代码窗口：高亮、悬浮类型、跳转、同名高亮（`--elaborate`，构建期跑 SubVerso）
[x] examples/demo 做成 lake 包，`--elaborate` 在示例上端到端跑通（Lean 4.33.0）
[x] Goal states：逐 tactic 显示，悬浮卡里，行号槽标出有状态的行。
    +9 KB / 74 states（示例），因为 goal 按 tactic 走而不是按 token。
    注意 SubVerso 给的是 tactic 执行**之后**的状态；"之前"没有声称，
    因为跨分支边界推不出来。
[ ] Proof-body ↔ tactic-block 对齐：数据已经在手上了——`tactics` 节点带
    的正是块的范围加上那一点的目标，就是对齐要用的东西。
[ ] 诊断：`span` 节点带 error/warning/info 和消息，同样已解析到但未导出。
[ ] 项目外的名字（mathlib、core）目前只有悬浮没有跳转；可以退化成 doc-gen4 链接。
