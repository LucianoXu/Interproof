[ ] 优化界面设计和元素
[ ] 发布到 PyPI（`pipx install interproof`）
[ ] Make a vscode plugin?
[ ] Better UI design (intractable buttons, etc.)
[ ] Call graph

[x] 代码窗口：高亮、悬浮类型、跳转、同名高亮（`--elaborate`，构建期跑 SubVerso）
[ ] 给 examples/demo 加 lakefile.toml + lean-toolchain，让 `--elaborate` 在示例上可跑
    （本机没有 Lean 工具链，未验证，所以没有先加进去）
[ ] Goal states：SubVerso 的 `tactics` 节点已带 startPos/endPos 和目标，
    现在被 subverso.py 跳过。接上它就同时拿到逐 tactic 的目标显示和
    proof-body ↔ tactic-block 对齐——同一次投资。
[ ] 诊断：`span` 节点带 error/warning/info 和消息，同样已解析到但未导出。
[ ] 项目外的名字（mathlib、core）目前只有悬浮没有跳转；可以退化成 doc-gen4 链接。
