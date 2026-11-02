# 自动测试

这里保留仍对应当前功能的回归测试，使用隔离资料目录和模拟Agent；不把真实模型会话或个人资料作为默认测试依赖。按改动选择相关文件，触发全量的条件只见[开发验证](../docs/full-loop-test-checklist.md)。

| 范围 | 主要文件 |
| --- | --- |
| 启动和HTTP边界 | test_server_runtime.py、test_fastapi_app.py、http_support.py |
| 分析、练习和作答 | test_learning_tasks.py、test_learning_loop.py、test_practice_*.py、test_prepared_*.py、test_question_review.py |
| 目录、标注与检索 | test_catalog_*.py、test_knowledge_*.py、test_annotation_*.py、test_bank_*.py |
| 画像和证据 | test_evidence_profile.py、test_evidence_stability.py、test_mapping_versions.py |
| 会话与阶段 | test_codex_bridge.py、test_task_bridge.py、test_study_workflows.py、test_agent_state.py |
| 图片、PDF和维护 | test_answer_images.py、test_paper_*.py、test_local_restore.py及迁移测试 |
| 前端 | 在web/src内与代码同目录的*.test.ts(x)，通过npm --prefix web test（Vitest）运行 |

例如只验证考点与题目的关联：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_knowledge_links.py -v
```

两个独立的画像类型/旧ID导航测试文件已合入test_evidence_profile.py，原有效用例保留。[旧文本](archive/README.md)不参与发现与执行。旧的真实模型/固定试卷验证脚本见[scripts归档](../scripts/archive/README.md)。

测试直接导入app包，mock/patch也指向实际模块。原server.py的隔离路径辅助函数已移入database_fixture.py，仅供既有夹具使用，不是应用入口。不要用删除仍有效的测试来掩盖功能回归。
