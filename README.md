<p align="center">
  <img src="web/public/brand/logo-wordmark.png" alt="做题龙 ZuoTiLong 项目标识" width="300" />
</p>

# 做题龙 · ZuoTiLong

基于已做试卷的考研数学复习工作台：上传、逐题分析、合并薄弱考点、少量补强练习、手写批改，再逐步积累学习画像。

**当前版本：v0.10.0 · Preview。** 面向个人本地使用，当前主要验证Windows。适合开始试用和反馈；完整的结束/续做流程、额外教材接入及部分性能优化仍在开发中。

**原创代码许可证：[MIT](LICENSE)。** 第三方依赖和题目资料保留各自许可，特别是PyMuPDF的AGPL／商业许可；详见[第三方声明](THIRD_PARTY_NOTICES.md)。

## 它能做什么

- 保存已做PDF，辅助识别/切题；Agent解释每题切入点、推导、注意事项，并区分可见错误和可能原因。
- 用统一原子考点关联题目；程序快速召回数学一/二/三题库，Agent判断本次补强的适配性，合并目标、控制题量。
- 按考点进入练习，上传手写照片或文字，明确提交后批改；区分独立完成与查看解析后的完成。
- 在考点树切换“已完成题目／全部题库”，由标签返回考点；画像可追溯到原卷和作答证据。
- 通用资料与个人工作区使用独立数据库、资源目录；支持资料导入/导出、个人归档及本地备份恢复。

所有可读原题都分析，但不为每道错题机械增加练习；未知不当薄弱，AI的可能原因不当确定结论。详细行为见[产品流程](docs/paper-review-workflow.md)。

## 安装与启动

准备Python **3.11或3.12**（推荐3.12）、能在终端调用且已登录的 **Codex CLI**。使用仓库附带的dist时无需Node.js，也无需在网页填写AI URL或API key。安装、模型调用需要网络；AI分析由Codex发送本轮材料到所选模型，页面和数据库在本机。

可选择下面任意一种安装方式。Python和Codex CLI的安装、登录要求见[配置教程第1节](docs/setup.md#1-检查环境)；Codex遵循[官方CLI文档](https://learn.chatgpt.com/docs/codex/cli)与[认证说明](https://learn.chatgpt.com/docs/auth)。

### 方法一：手动安装

1. 下载本仓库ZIP并解压，或克隆：

   ```powershell
   git clone https://github.com/Ecankk/ZuoTiLong.git
   cd ZuoTiLong
   ```

2. 在项目目录打开终端，执行`python --version`、`codex --version`和`codex login status`确认环境；尚未登录时执行`codex login`，由本人完成授权。
3. 首次双击`setup_mathlens.bat`安装依赖，看到`Setup complete`后双击`start_mathlens.bat`。
4. 浏览器自动打开实际本地地址；端口自动回退，重复启动复用已有服务。以后直接双击`start_mathlens.bat`即可。
5. 按下节[首次资料准备](#首次使用需要哪些资料)导入题库、考点目录和标注，然后开始复习。

完整命令、数据位置和排错见 **[配置与首次使用](docs/setup.md)**。

### 方法二：让Agent安装

先按方法一的第1步获取仓库，在项目根目录打开Codex或其他代码Agent，发送以下内容：

```text
请阅读 docs/setup.md，按其中的安装步骤和配置Agent执行边界配置并运行本项目：
1. 检查 Python 3.11/3.12、Codex CLI 和登录状态；复用可用环境，安装缺少的项目依赖。
2. 保留已有数据，用 start_mathlens.ps1 -NoBrowser 启动。
3. 用实际地址的 /api/health 和首页验证启动，告诉我访问地址。
4. 检查题库、考点目录和标注是否就绪；有我提供的资料就按教程导入，缺少则列明。
登录授权由我完成；不要发起学习任务、从头重标题库或提交/推送代码。
```

Agent完成后，在浏览器打开它给出的地址；以后仍双击`start_mathlens.bat`启动。两种安装方式使用相同的应用和资料配置，不需要安装两遍。

配置用聊天与应用专用的学习会话分别使用。实际复习由网页按钮派发任务，应用持续复用本人的学习会话，不要求用户用聊天指令串流程。运行期间不要同时从Desktop/CLI控制该学习会话。

三类Agent的指令入口分别维护：

| 用途 | 指令入口 |
| --- | --- |
| 安装配置：检查环境、安装依赖、启动和导入资料 | [docs/setup.md](docs/setup.md) |
| 应用内学习：分析、选题、批改、总结 | 后端下发的任务提示和JSON Schema，以及通过`read_skill`读取的[项目Skill](.agents/skills/)；机制见[学习Agent协议](docs/agent-workflow.md) |
| 代码开发：修改代码、选择测试、维护文档 | [项目架构](docs/backend-architecture.md)与[开发验收](docs/full-loop-test-checklist.md)；维护者的本机开发约定不随仓库发布 |

## 首次使用需要哪些资料

**项目提供程序、学习Skill、纯净考点目录和题目标注索引；用户自备题目材料、已做试卷、手写作答和Codex账号。** 仓库不附带维护者的运行数据库或个人学习记录，题目原图也不捆绑分发。

| 资料 | 用途 | 谁提供／如何获取 |
| --- | --- | --- |
| 本地题库及参考 | 练习题干、答案、解析 | 用户自行准备；当前支持S01数一/二/三真题导入，见[题源目录](docs/question-sources.md) |
| 通用考点目录JSON包 | 统一的学科/章节/原子目录与定义 | 项目提供[resources/shared/catalog.json](resources/shared/catalog.json)，在设置预览并导入 |
| 题目标注索引JSON包 | 考点与题目关联、就绪召回 | 项目提供[resources/shared/question-index.json](resources/shared/question-index.json)，准备匹配版本的题库和目录后导入 |
| 已做试卷PDF、本人手写照片或解题文字 | 诊断与后续批改 | 用户提供，仅保存在本人的工作区 |
| Codex CLI与登录账号 | 执行分析、选题、批改 | 用户自行安装和登录；不随项目提供凭据或模型额度 |

按[配置教程第3节](docs/setup.md#3-配置题库考点和标注)依次准备。包的覆盖、散列与固定题源版本见[通用资料说明](resources/shared/README.md)。题目材料必须由用户导入，下载项目不会自动获得完整题库；不要让Agent为安装而从头重建整库。S02/S03教辅资料目前仍未正式接入。

资料来源、版本和边界统一见[题源目录](docs/question-sources.md)，不把题目正文随代码打包。

## 日常复习

1. 在设置选择备考数学一/二/三、真题显示保护和笔迹约定。
2. 上传一份已完成的试卷PDF，等待本地识别/切题；在网页连接Codex，逐题分析后自动分阶段整理考点、筛选补强题。
3. 按考点打开少量练习，做完后上传手写照片或输入解题内容，点击“提交作答并批改”。
4. 查看批改反馈、考点树和学习画像；需要时追加练习或手动生成整卷总结。

分析、整理、选题、批改各自分阶段执行；用户不维护JSON或逐项确认错因。默认黑字为考试作答，红字为事后批改，可在设置修改。照片先暂存，提交才批改；已有练习可追加。同类别真题按设置确认后展示，本地题库可直接浏览，预留卷排除日常选题。

学习会话首次默认请求`gpt-6-luna / xhigh`，之后沿用保存的设置；模型须由账号实际提供。模型切换、会话释放/恢复及结果契约见[Agent协议](docs/agent-workflow.md)。

## 数据与隐私

默认运行数据放在源码外的`%LOCALAPPDATA%/ZuoTiLong/`：

```text
library/library.db                   通用考点、题库、标注和出处
library/bank-assets/                  本地题干、答案和解析
workspaces/default/learning.db        本人的试卷、练习、作答和画像
workspaces/default/agent-session.db   本人的会话状态
```

学习连接只读通用库、写个人工作区；资料更新使用独立维护入口。新工作区能复用通用资料，学习记录从零开始。旧项目.mathlens首次默认启动时复制迁移并保留原目录。Windows打包应用可能映射AppData路径，实际配置查询和干净重测见[配置教程第5节](docs/setup.md#5-数据位置与干净重测)。

应用内学习Agent的任务指令由后端和[.agents/skills/](.agents/skills/)维护，随项目同步。维护者本机的`AGENTS.md`是私人开发约定，保留在本地并由Git忽略，不是安装或学习任务的必备文件；个人全局Agent配置和登录凭据也不发布。

Git同步源码、上述Agent约定与Skill、测试、公开文档、依赖/启动脚本及免Node启动所需的dist。运行双库、个人工作区、原题资源、会话、日志、备份、临时文件和docs/local均不提交，规则见[.gitignore](.gitignore)。完整本地备份含个人内容，不能作为共享资料或发行包；共享只使用核对过的纯净导出包。

## 当前限制

- 复杂手写、跨页/多栏切题和数学判断仍可能有误；材料不清时需要必要补图，真实效果按试用反馈完善。
- 总结目前手动触发；“结束本轮→未做题统一留存→下次续做”的完整入口尚未实现。
- 考点及题目准备已有首轮核对，仍保留争议/缺口，不宣称全库数学零错误或当年官方考纲完整认证。
- 考点关联页面加载偏慢待优化；Desktop同时接管学习会话、跨机和其他平台尚未完整验收。
- 已提供纯净考点和标注包；安装/导入的开发验证不代替本人自然学习体验，首次使用按[人工清单](docs/manual-test-checklist.md)完成一轮，不把本机运行等同于所有用户环境已验收。

这些边界不阻止已有功能独立试用；首次体验用一份已做卷和一道本人手写即可，见[人工清单](docs/manual-test-checklist.md)。

## 开发与项目结构

前端为React 19 / TypeScript / Vite 7 / 本地KaTeX；后端为FastAPI / Uvicorn / SQLite。浏览器通过HTTP与后端通信，后端通过本机`codex app-server`及固定任务契约接入学习Agent；当前用HTTP轮询同步状态。

```text
app/                后端：api、services、learning、knowledge、bank、storage等
web/                前端源码；dist/为预构建页面
.agents/skills/     学习任务的方法与交付说明
scripts/、tests/    资料工具、有效测试；archive为历史文本
```

修改前端时，使用满足web依赖要求的Node.js，在web目录执行`npm ci`、`npm run dev`或`npm run build`；Vite开发代理读取实际后端地址。修改后端从[项目架构](docs/backend-architecture.md)及受影响代码开始，按[开发验收](docs/full-loop-test-checklist.md)选择验证，不默认重跑模型或全库审查。

[文档导航](docs/README.md) · [配置教程](docs/setup.md) · [后端结构](docs/backend-architecture.md) · [题源接口](docs/bank-source-interface.md)

## 参考与致谢

感谢[11408Advance-mcp](https://github.com/hanserdesu/11408Advance-mcp)的数学考点资料、[kaoyanshuxue](https://github.com/lx-ruc/kaoyanshuxue)的真题资料结构，以及[AI错题本error-notebook](https://github.com/Jasmine-Coder-Dev/error-notebook)、[kaoyan-quiz](https://github.com/roizenken-design/kaoyan-quiz)、[math-question-bank](https://github.com/justcodeit404/math-question-bank)的产品或题库组织参考。

题源接入、目录资料来源与设计借鉴分别记录；致谢不表示全部项目已经接入，也不替代原始内容授权。具体用途、作者链、依赖许可及S02/S03状态见[第三方声明](THIRD_PARTY_NOTICES.md)和[题源目录](docs/question-sources.md)。
