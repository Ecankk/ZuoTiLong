# 本地配置与首次使用

本文件是用户和配置Agent共用的安装入口。使用Windows原生Python和Codex CLI运行本地应用；安装按本文执行，应用内学习任务使用独立的[Agent协议](agent-workflow.md)和项目Skill。需要修改项目代码时再查[项目架构](backend-architecture.md)与[开发验收](full-loop-test-checklist.md)。

两种安装方式：

| 方式 | 适用 | 入口 |
| --- | --- | --- |
| 桌面安装包（Windows 10/11 x64，试水版尚未发布） | 普通用户；不需要Python/Node | 运行安装包→首次打开选数据位置（默认`%LOCALAPPDATA%\ZuoTiLong`）→等待题库准备完成；Codex仍需本人安装官方原生`codex.exe`并`codex login`，应用的新手引导和设置页可重新检查、指定路径 |
| 源码目录（下文） | 开发、题库维护 | 本文第1–6节 |

桌面版的构建步骤见`scripts/packaging/README.md`（冻结后端与题库种子）和`src-tauri/`（外壳与NSIS安装包，`npm --prefix src-tauri run build:nsis`）；构建产物在被忽略的`build/`下，不进版本库。桌面版只支持官方原生安装的`codex.exe`，npm安装的`codex.cmd`无法可靠启动。

## 1. 检查环境

在项目根目录打开PowerShell：

```powershell
python --version
codex --version
codex login status
```

| 依赖 | 要求 |
| --- | --- |
| Windows | 当前验证的平台；BAT和PowerShell启动器面向Windows |
| Python | 3.11或3.12，推荐3.12；安装时启用PATH和pip |
| Codex CLI | 终端能找到`codex`，已登录可用账号；仅安装Desktop不保证CLI在PATH |
| 网络 | 首次安装下载依赖，AI分析由Codex访问模型服务；页面和数据库在本机 |
| Git | 克隆代码/题源时使用；下载ZIP并解压也可以 |
| Node.js/npm | 普通使用已有dist无需安装；修改前端或选择npm安装Codex时才需要 |

Codex安装遵循[官方CLI说明](https://learn.chatgpt.com/docs/codex/cli)。尚未登录时执行`codex login`，由本人在浏览器完成；登录检查见[官方认证说明](https://learn.chatgpt.com/docs/auth)。应用沿用本机登录，不要求填写AI URL或API key。模型调用需要账号实际具备相应权限和额度。

如果`python`不是3.11/3.12，可检查`py -3.12 --version`。不要在不匹配的解释器上继续安装。安装或登录后重新打开终端和启动器，使PATH/登录状态生效。

## 2. 安装并启动

获取本仓库源码或ZIP，解压后保留app、dist、scripts及启动文件的相对位置。

普通用户首次双击`setup_mathlens.bat`，看到`Setup complete`后，再双击`start_mathlens.bat`。安装脚本创建.venv并按requirements-ocr.txt安装后端、PDF和OCR依赖。以后直接运行start，不必重复安装。

配置Agent使用等价的非交互命令，避免BAT末尾pause等待输入：

```powershell
python -m venv .venv
python -m pip --python .venv/Scripts/python.exe install -r requirements-ocr.txt
.\start_mathlens.ps1 -NoBrowser
```

已存在可用.venv时复用，不删除或重复创建。若前一步确认使用的是`py -3.12`，相应地用它替换两行命令开头的`python`。依赖已满足且未修改时不重复安装。

启动器显示`MathLens is ready`及实际URL，默认尝试4173，端口不可用时回退。以显示地址为准；服务后台运行，重复启动复用健康实例。普通用户启动会自动打开浏览器，`-NoBrowser`只启动服务。

手动启动入口：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app --host 127.0.0.1 --port 4173 --auto-port
```

当前交付方式是源码目录加预构建dist；不要把`pip install .`、缺少dist的Python wheel或Vite preview当成完整安装入口。

## 3. 配置题库、考点和标注

**全新安装不会继承维护者的运行库或个人记录。**项目提供纯净考点目录和标注索引文件，用户另行准备原始题目材料，完成导入后才有可用补强题池。

| 资料 | 如何准备 |
| --- | --- |
| 本地题干/答案/解析 | 用户自行准备支持的S01资料，来源及固定版本见[题源目录](question-sources.md) |
| 通用考点目录JSON包 | 使用项目附带的[resources/shared/catalog.json](../resources/shared/catalog.json)，在设置的“通用考点目录”预览、核对后导入 |
| 题目标注索引JSON包 | 使用项目附带的[resources/shared/question-index.json](../resources/shared/question-index.json)，在设置的“题目标注索引”预览、核对后导入；应匹配本地题目和考点版本 |

两份文件的固定版本、包散列、覆盖和许可见[通用资料说明](../resources/shared/README.md)，不含个人记录或题目正文。配置Agent应复用它们；缺少用户的原题材料时报告缺项，不自行整库重标。

当前索引匹配S01版本`196dc9d2d8271978a030a3721a828c8723cd3864`。用户自行取得该版本的题源目录；已有本地目录就复用。获取方式示例：

```powershell
git clone https://github.com/lx-ruc/kaoyanshuxue.git 'D:\MathMaterials\kaoyanshuxue'
git -C 'D:\MathMaterials\kaoyanshuxue' checkout 196dc9d2d8271978a030a3721a828c8723cd3864
```

S01导入器要求给出包含`kaoyan_math_images`的本地仓库根目录：

```text
你的题源目录/
└── kaoyan_math_images/
    ├── 数学一/answers.json及题图目录
    ├── 数学二/answers.json及题图目录
    └── 数学三/answers.json及题图目录
```

在没有学习任务执行时导入：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/agent_tasks.py import-bank 'D:\MathMaterials\kaoyanshuxue'
```

示例路径需替换为本人实际目录。随后在网页设置先选择catalog.json预览并确认导入，再选择question-index.json预览并确认导入；可从“考点树→全部题库”查看关联。空工作区不应因此出现个人已完成记录。若索引预览匹配为0，核对题源版本、材料和目录，不能通过改散列强行导入。有效ready标注才使题目进入默认补强池，待核题不强行计入。S02/S03目前尚未正式接入。

## 4. 开始一轮复习

1. 在设置选择备考数学一/二/三和同类别真题显示保护，可修改默认笔迹约定。
2. 上传已做试卷PDF，等待本地识别/切题，核对题号后点开始分析。默认黑字是考试作答，红字是事后批改；已确认空白保留未作答事实。
3. 应用通过本机Codex为每个AI任务新开一次会话，无需手动打开会话。逐题分析后，应用分阶段整理考点并筛选少量练习。
4. 按考点进入补强练习。照片/文字先暂存，明确点击提交后才批改；可以追加练习。
5. 查看反馈、考点树和画像，需要时手动总结。当前尚无完整的“结束本轮→未做题统一留存→下次续做”入口。

模型与推理强度分两档，在设置中选择：判断档（分析试卷、单题复核、批改等）默认gpt-6-luna/xhigh，整理档（选择练习、整理考点、总结）默认gpt-6-luna/high。可选项来自本机Codex实际返回的模型列表；所选项不可用时任务失败并提示，应用不会换用其他模型。若账号不提供该模型或所需app-server能力，报告实际错误，按[Agent协议](agent-workflow.md)处理。

本地保存不等于模型离线运行：AI阶段会通过Codex向所选模型发送本轮需要的材料。

## 5. 数据位置与干净重测

默认通用库在`%LOCALAPPDATA%/ZuoTiLong/library/library.db`，个人库在`%LOCALAPPDATA%/ZuoTiLong/workspaces/default/learning.db`。Windows打包应用可能将AppData映射到自己的LocalCache；以实际配置输出为准：

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "from app.config import AppConfig; c=AppConfig.from_env(); print(c.data); print(c.library_dir)"
```

首次默认启动会复制迁移旧项目.mathlens并保留原目录。完整本地备份含个人内容，不用作共享资料。

要从零体验且保留旧数据，在新终端设置一个新工作区并指向已有通用库：

```powershell
$env:MATHLENS_DATA_DIR = 'D:\ZuoTiLongData\workspaces\fresh'
$env:MATHLENS_LIBRARY_DIR = 'D:\ZuoTiLongData\library'
.\start_mathlens.ps1 -NoBrowser
```

第二个路径必须替换为实际已有通用库目录；该目录下应有library.db及对应资源。环境变量只对当前终端及其子进程生效；应用不自动读取.env。首次创建后，workspace.json保留该工作区的库位置。关闭这个终端后按默认方式启动可回原工作区；不删除个人表或复制旧执行票据。

## 6. 给配置Agent的执行边界

阅读本文件，按第1–3节检查/配置；本次仅负责安装和运行，不开展代码开发或学习分析。环境已满足就复用；缺少Python、Codex登录或资料包时明确说明缺项。登录与必要账号授权交本人完成，不输出凭据内容。

启动后请求实际URL的`/api/health`，应有ok=true和当前版本；核首页、题库及考点目录的读取状态。新工作区应无个人学习记录；只报告实际导入了什么，不把本机别的库当成仓库自带资料。到本地启动验证通过即结束，不自动上传本人试卷、发起真实模型任务、重标全库、恢复长期Goal或提交/推送代码。

需要数学体验时再用[人工清单](manual-test-checklist.md)。常见问题先看实际工作区中的server.stderr.log和server.stdout.log：命令不存在查PATH，连接失败查CLI登录与所选模型是否可用，无补强题查资料/有效标注/预留设置；不要以重建会话或删除数据库作为默认修复。
