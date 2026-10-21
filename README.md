# MathLens

本地优先的考研数学一试卷诊断与针对性复测工具。

第一版围绕一个最小闭环：

```text
导入已完成试卷 → 逐题诊断 → 从本地题库检索 → 针对性小测 → 更新个人画像
```

## 启动

需要 Python 3.11+，第一版只使用 Python 标准库：

```bash
python server.py
```

浏览器打开 `http://127.0.0.1:4173/`。

Windows 用户可以直接双击项目根目录的 `start_mathlens.bat`，脚本会启动服务并自动打开浏览器。关闭名为 `MathLens Server` 的命令行窗口即可停止服务。

首次启动会在 `.mathlens/` 中创建 SQLite 数据库和示例数据。真实资料放在 `.mathlens/`，不会进入 Git。

## 当前能力

- 导入已完成试卷 PDF，并保存原始文件到本地待确认队列
- 试卷、题目、错因、解题环节和复测记录
- 本地题库检索和筛选
- 针对单题建立 3～5 题的检验小测
- 记录正确率、用时、自信程度和重复错误
- 用证据更新个人画像：未验证、不稳定、基本掌握、迁移通过
- 导入自有题库 JSON

在“本地题库”页可以直接导入 `questions.json`；兼容 `stem`、`content`、`question`、`tags`、`keywords`、`chapter` 等常见字段。

## 题库 JSON 示例

```json
[
  {
    "id": "local-001",
    "source": "我的题库",
    "stem": "定积分换元：判断换元变量与上下限",
    "answer": "按新变量同步修改上下限",
    "explanation": "先写换元关系，再检查上下限与符号。",
    "tags": ["定积分", "换元", "上下限联动"],
    "fingerprint": {
      "objects": ["定积分"],
      "method": ["换元积分"],
      "stages": ["切入", "计算"]
    },
    "difficulty": 2
  }
]
```

## 后续接入 Codex

第一版先保证题目数据和复测闭环。下一阶段将由本地 server 启动 `codex app-server`，把单题诊断、指纹提取、题库筛选和复测总结作为受控工具暴露给 Agent。
