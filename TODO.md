[ ] 优化界面设计和元素
[ ] 发布到 PyPI（`pipx install interproof`）
[ ] Make a vscode plugin?
[ ] Call graph
[?] Differentiate between mention and correponding. Corresponding should be one to one, and check during interproof check.
[x] Not all comments are detected. -- and /-! are not detected.
    `--` above a declaration now introduces it, `/-!` without a `##` heading is
    module prose and ends the declaration above it, and a trailing `--` after
    code still belongs to the line it trails.