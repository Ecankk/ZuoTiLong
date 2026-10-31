# 历史验证脚本

这些脚本已退出活动脚本目录，按原文以`.py.txt`保存，仅用于追溯，不是可直接运行的当前验收入口。默认验证方式见[开发验证](../../docs/full-loop-test-checklist.md)，自动测试见[tests](../../tests/README.md)。

| 原脚本 | 归档原因 |
| --- | --- |
| [verify_codex_bridge.py](verify_codex_bridge.py.txt) | 旧自由对话/图片连接实验，会创建真实模型会话；当前阶段机制由隔离桥接测试覆盖 |
| [verify_codex_model_sync.py](verify_codex_model_sync.py.txt) | 一次性双客户端模型同步实验，会修改实验会话设置；不属于日常自动回归 |
| [verify_learning_tools.py](verify_learning_tools.py.txt) | 旧学习协议端到端实验，包含早期报告格式和直接写入假定 |
| [verify_local_loop.py](verify_local_loop.py.txt) | 固定22题与旧练习展示字段的历史检查，不能作为当前通用验收 |
| [prepare_browser_fixture.py](prepare_browser_fixture.py.txt) | 只复制部分材料的旧浏览器夹具生成器，不适用于当前固定材料/知识依赖 |

需要真实模型或本人体验时，按当前任务选一个代表流程，不重新启用整套历史脚本。
