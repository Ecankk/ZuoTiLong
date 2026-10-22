# MathLens

本地考研数学一试卷诊断工具：上传已完成试卷，保留原卷作答证据，分析可能的错误原因，从现有题库选择分环节检验，再按真实作答更新个人画像。

产品定位是 **Agent 的可视化数学诊断工作台**：Agent 阅读原卷和题库，讨论、选题并讲解；程序负责裁切、保存与展示。分类仅供浏览，不用代码相似度替代教学判断。项目工作约定见 [AGENTS.md](AGENTS.md)，持续网页会话的实现边界见 [交互设计](docs/agent-first-design.md)。

## 本地使用

Windows 首次安装需要 Python 3.11 或 3.12，双击 `setup_mathlens.bat` 安装项目虚拟环境与本地 OCR 依赖。随后双击 `start_mathlens.bat`，打开 <http://127.0.0.1:4173/>。

已经配置好环境的机器可直接启动。启动器在后台运行服务，输出日志保存在 `.mathlens/server.stdout.log` 与 `.mathlens/server.stderr.log`；终端不再需要停留在服务进程中。重复启动复用健康的当前版本服务。前端已构建到 `dist/`，普通使用无需安装 Node.js。

若手动启动：

```powershell
.\.venv\Scripts\python.exe server.py --host 127.0.0.1 --port 4173
```

页面中“今日工作”展示原卷与诊断、针对性检验和初始画像。先做优先检验，每题可以只回答入手、参数范围或某一步计算。已看过解析的练习会记录答案暴露情况，不计入独立检验成功。

v0.4.1：在右侧 Agent 工作区点击“连接 Codex”，使用本机已登录的 Codex CLI（找不到时可通过 `MATHLENS_CODEX_BIN` 指定可执行文件）。自动建立并复用一个学习专用会话。默认跟随主区正在查看的试卷/题目，随消息附上发送时的页面快照和原卷区域图；可取消跟随并手动关联其他题目。页面快照包含当前检验环节、已展开内容的名称，不采集未提交草稿或其他应用内容，浏览页面不会自动发消息。右侧面板可收起，窄屏以抽屉打开。发送后输入锁定，等完整反馈结束再继续；停止或失败后需要完成原请求，不能越过未完成轮次。刷新网页不会丢失状态。

首次需要安装 Codex 并完成 `codex login`；不需要在网页另填模型 URL 或 API key。会话记录保存在 `.mathlens/agent-session.db`，Codex 的诊断日志在 `.mathlens/codex.stderr.log`。连接或恢复失败时网页显示原因；它不会另建新会话来假装恢复成功。

若 Windows 沙箱拒绝启动工具，Codex 可能申请单次授权；网页会显示实际命令与原因，由用户允许或拒绝。应用不会自动批准，也不会关闭沙箱来消除提示。

## 当前能力与边界

- React + TypeScript + Vite 前端，Python HTTP 服务，SQLite；只监听本机，不依赖线上演示站点。
- 数字 PDF 提取文字与坐标；扫描件通过 RapidOCR/ONNX 在本地识别题号和文字草稿，并做题号区域补识别。按文件 hash 与管线版本缓存。
- 逐题支持多个页内证据区域，保留题干、手写作答与批改；不把 OCR 草稿当标准答案，也不把文字识别分数当准确率。
- Agent 在项目文件夹中读取页图、核对题目与学生作答、提出原因假设、选择已有检验题，通过受校验的结构化报告写回应用。用户连接后由本机 Codex 处理网页输入。
- 网页无需另填模型 API key。CLI 所用模型仍需用户自己的登录或服务能力。具体流程和命令见 [Agent 工作流](docs/agent-workflow.md)。
- 支持从个人本地 `lx-ruc/kaoyanshuxue` 目录导入数学一题图、解析及元数据；外部题目资源放在 `.mathlens/bank-assets/`，不随代码分发。
- 检验作答实际保存。明确简单的允许答案可自动核对；其他表达等待 Agent 评价。不会将未识别表达自动判错，或将一次答对标记为稳定掌握。
- 画像按原卷与检验事件累计，保留错误、成功、未展示及原因待查状态；单卷不能推断长期稳定性、心态或耗时。
- 报告检查文件 hash、完整题号与区域边界；重复报告及带请求标识的重复提交不重复累计。重新提取不覆盖 Agent 已审阅的诊断。

首次真实样本已经完成 4 页、22 题的自动定位与 Agent 视觉核对。它是个案验证，不能据此宣称对所有卷型、手写或公式都达到同样准确率。旧版本纯正则切题的缺陷已修正并纳入回归测试。

## 数据与个人资料

原始试卷、题库图片、SQLite、报告、任务及本地备份都保存在 `.mathlens/`，已从 Git 排除。`tmp/` 中的隔离测试数据也不进入仓库。现有数据库自动增加字段和表；默认不再向新库填入示例数据，旧示例在正常界面隐藏，设置 `MATHLENS_DEMO=1` 可启用示例模式。

应用代码与第三方题目内容的授权分别处理。KaTeX 的 MIT 许可随离线公式排版资源保留。

## 开发与验证

```powershell
# 后端与数据事件测试（独立临时数据库）
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 前端
cd web
npm install
npm run build
```

`scripts/verify_local_loop.py` 对已导入的首个真实报告执行只读 HTTP 验收，不写入检验作答。浏览器提交测试采用独立的 `tmp/browser-fixture`，不能把模拟回答写进个人数据库。

- [Agent 任务、报告契约与检验评价](docs/agent-workflow.md)
- [参考项目源码审查](docs/reference-source-review.md)：记录改造前的基线缺陷，不代表当前代码仍全部存在这些问题。
- [资料库候选与完整性检查](docs/question-bank-options.md)
- [现有68类考点的粒度审查](docs/bank-topic-review.md)
- `scripts/audit_references.py`、`scripts/audit_candidate_banks.py`：可重复的数据与管线检查。历史结果文件记录的是当时版本。
