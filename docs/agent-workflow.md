# 本地 Agent 工作流

网页通过本地 HTTP 服务读取 SQLite。Agent 在项目目录读取任务包、阅读原卷图片、检索本地题库，再提交结构化结果；用户无需在网页里另填模型 API key。模型的登录、视觉能力由用户选择的 CLI 提供，应用本身没有后台模型调用。

## 当前支持

工作约定在根目录 `AGENTS.md`。选题由 Agent 阅读后决定，源分类只作目录导航。不要把题库同类、文本相似或尚未审定的默认难度当作选择条件。持续网页对话的设计及尚未实现部分见 [Agent 交互设计](agent-first-design.md)。

1. 网页上传 PDF 后自动运行本地 OCR/文字提取和切题，在 `.mathlens/tasks/<paper_id>/request.json` 写出任务、源文件 SHA256、完整页图及逐题区域。
2. Agent 阅读页图，区分题干、黑字作答和批改；必要时针对影响结论的疑点询问用户。OCR 是草稿，不能代替图像证据。
3. Agent 通过题库元数据和资源图片选择已有题，创建入手、建系、运算、最终处理等分环节检验。网页收集真实作答。
4. 明确、简单的数值回答可按报告给出的允许答案核对；其他回答进入等待评价，不自动判错。Agent 再次运行 `pending` 读取作答并评价，网页每 5 秒刷新。
5. 每次评价生成证据事件。画像由原卷事件和检验事件汇总；看过参考解析的题不计入独立检验成功。

网页点击“连接 Codex”后，服务通过本机 `codex app-server` 建立一个专用会话，沿用本机登录与默认模型，不需填写 AI URL/API key。重连恢复持久保存的同一个会话。也可以独立使用下述 CLI 命令，但不要在网页处理过程中同时向其专用会话输入。

用户发送讨论或在已连接状态提交检验/完成试卷切分后，网页等待该轮完整最终反馈，期间禁用下一步学习输入，后端同样拒绝写入。授权和 Agent 必要追问是当前轮次的补充，不是新轮次。失败/断线保留输入锁与记录，重连核对原轮次后可重试。模型能力和服务可用性仍由本机 Codex 登录提供。

## 命令

以下以 Windows 项目虚拟环境为例；在已安装依赖的其他环境可替换为 `python`。

```powershell
# 新原卷：SHA256 去重、自动切题、生成 Agent 任务包
.\.venv\Scripts\python.exe -X utf8 scripts/agent_tasks.py prepare "C:\path\completed-paper.pdf"

# 首次导入个人已有的外部题库资源；后续不必重复
.\.venv\Scripts\python.exe -X utf8 scripts/agent_tasks.py import-bank "F:\kaoyan\references\kaoyanshuxue"

# 查看任务包和等待评价的真实作答
.\.venv\Scripts\python.exe -X utf8 scripts/agent_tasks.py pending

# 新会话恢复个人资料、最新诊断、真实作答和记忆文件入口（只读）
.\.venv\Scripts\python.exe -X utf8 scripts/agent_tasks.py context

# 自选分类范围浏览，查看返回的原图；不进行自动选题（只读、带分页）
.\.venv\Scripts\python.exe -X utf8 scripts/agent_tasks.py catalog --topic "曲线积分" --topic "曲面积分"
.\.venv\Scripts\python.exe -X utf8 scripts/agent_tasks.py catalog --id math1-2021-12

# Agent 写好报告后，由应用校验并写入数据库
.\.venv\Scripts\python.exe -X utf8 scripts/agent_tasks.py apply <paper_id> ".mathlens\agent-result.json"

# 对一个已提交、尚未评价的检验作答提交评价
.\.venv\Scripts\python.exe -X utf8 scripts/agent_tasks.py assess <attempt_id> ".mathlens\assessment.json"
```

示例自然语言指令：

> 检查 MathLens 的 pending 任务。先读 request.json 和原始页图，逐题核对题干与作答；从本地数学一题库挑选能区分错因的检验环节。不要虚构分数、时间或检验结果。对已经提交的作答给出有证据的评价，然后通过命令写回应用。

## 报告契约

报告至少包含：

- `author`、`method`、`source_sha256`、`expected_count`；源文件 hash 必须匹配，题号必须完整且唯一。
- `questions`：`number`、`subject`、`stem`、`max_score`、`score_earned`（未知为 null）、`correctness`、`observation`、`reference_answer`、`reference_reasoning`。
- 每题 `regions`：多个 `{page,bbox:[x0,y0,x1,y1],role}`；坐标为原 PDF 点，页码从 1 开始。支持 `supplemental_work`，用于跨题边界书写的同题补充计算。所有区域必须落在对应页面内。
- 每题 `fingerprint`：对象、条件特征、目标、切入线索、方法、操作、微技能、检查点及版本。题目要求与学生表现分开。
- 每题 `hypotheses`：`id,label,evidence,alternative,correction`。错误结果不足以唯一确定原因时保留竞争假设。
- 每题 `skill_events`：`skill_id,label,kind`，kind 为 `exam_error/exam_success/hypothesis/incomplete`。没有展示作答不等于不会；自查修正可同时保留错误与成功证据。
- `probes`：`id,question_number,bank_id,skill_id,skill_label,targets,prompt,discriminates,expected,priority`；可选 `accepted` 只用于简单且无歧义的答案，不认可用字符串匹配代替开放推导的评价。
- `summary,score_status,priorities,limitations` 用于显示本卷结论、待核分值与来源边界。

Agent 评价文件为 `{ "correct": true/false, "feedback": "具体核对依据", "author": "评价者" }`。已经评价的作答拒绝重复评价；本版本暂未提供撤销评价界面，如需纠错先备份并由维护者显式更正事件。

原卷、题库图片、分析报告、任务和个人画像均位于被 Git 忽略的 `.mathlens/`。试题来源与授权独立于应用代码；题库仅从个人本地目录导入，不自动随项目分发。

## 测试边界

`python -m unittest discover -s tests -v` 使用独立临时数据库。浏览器测试可以运行 `scripts/prepare_browser_fixture.py` 生成 `tmp/browser-fixture`，设置 `MATHLENS_DATA_DIR` 后在其他端口启动。禁止将测试作答提交到真实个人数据库。
