# Windows x64 后端 onedir 构建

本入口对应桌面 A 协议。只构建后端和 `build/desktop-stage`，不运行 Tauri/安装器，不连接用户数据或 Codex。`build/` 内所有文件均为本机构建产物，不进 Git；首建时创建仅含 `*` 的 `build/.gitignore`。不要复制已有 `.venv`。

## 固定环境与依赖

使用官方 **CPython 3.12.10 x64**。锁包含运行依赖及 PyInstaller 构建工具的全部直接/传递依赖，共 42 个 wheel（包含引导 pip 25.0.1）。只支持 Windows x64 CPython 3.12，本锁不用于其他平台。

```powershell
New-Item -ItemType Directory -Force build | Out-Null
Set-Content build/.gitignore '*' -Encoding ascii
& 'C:\Users\29581\AppData\Local\Programs\Python\Python312\python.exe' -m venv build/desktop-venv

# 首次可联网下载；已有wheelhouse时跳过下载，后面安装全离线。
build/desktop-venv/Scripts/python.exe -m pip download --only-binary=:all: --require-hashes -r scripts/packaging/requirements-win-x64-py312.lock --dest build/desktop-wheelhouse
build/desktop-venv/Scripts/python.exe -m pip install --no-index --find-links build/desktop-wheelhouse --require-hashes -r scripts/packaging/requirements-win-x64-py312.lock
build/desktop-venv/Scripts/python.exe -m pip check
```

`wheels-win-x64-py312.json` 列每个 wheel 的文件名、版本、大小与 SHA256。wheel 二进制保留在忽略的 `build/desktop-wheelhouse/`，不随安装器分发。构建前会核对已安装版本及每个 wheel 的散列。该 lock 的 Pillow 为 **12.3.0**（满足 `<13`），PyInstaller 为 **6.22.3**；不按开发机已安装的 Pillow 13 冻结。

若明确升级依赖，在**另一个全新wheelhouse**中先按 `requirements-ocr.txt` 和 `pyinstaller>=6,<7` 解析下载，再运行 `lock_wheels.py --wheelhouse <目录>`。检查差异，重新安装、pip check及执行完整冻结烟测后才提交锁。该命令不自行下载、不执行 wheel，只读取顶层 `.dist-info/METADATA` 并计算散列（排除 setuptools vendor metadata）。

## 构建与布局

```powershell
build/desktop-venv/Scripts/python.exe scripts/packaging/build_backend.py
# E交付正式种子后用显式参数，工具要求seed包含manifest.json。
build/desktop-venv/Scripts/python.exe scripts/packaging/build_backend.py --seed '<已批准种子目录>'
```

默认使用一道虚构题的合成种子，`build-manifest.json.synthetic_seed=true`；**它只用于烟测，不能当正式题库发行**。不读取或复制主数据。脚本设置隔离构建数据变量；原有相同名字的开发数据环境不参与构建。可从任意 cwd 调用脚本，项目路径以脚本位置解析。

```text
build/desktop-stage/
  build-manifest.json
  backend/
    mathlens-backend.exe
    _internal/                  # 与exe一同携带，不能只复制exe
      app/agent/runtime_agents.md
      rapidocr_onnxruntime/     # YAML、检测/分类/识别ONNX模型
      ... native DLL/pyd/metadata
    THIRD-PARTY-NOTICES.txt
    LICENSE-MathLens.txt
    third-party-licenses/       # wheels许可、完整AGPL-3.0、Python及项目通知
    source/mathlens-<sha>.zip   # 干净Git源码构建才生成
  resources/
    dist/
    .agents/skills/mathlens-<name>/SKILL.md  # 七份
    docs/agent-workflow.md
    docs/question-sources.md
    docs/bank-source-interface.md
    library-seed/
```

冻结入口 `backend_entry.py` 使用 `freeze_support()` 后直接调用 `app.cli.main()`，不会以 `sys.executable -m app` 再启动自身。console模式保留父子stdin/stdout/stderr，外壳负责隐藏窗口。spec为onedir、无UPX；显式收集模板、RapidOCR/JSON schema数据、ONNX/OpenCV/NumPy/Shapely/Pillow/MuPDF原生库，并沿PyInstaller官方/贡献hooks补依赖。

脚本仅替换带本工具 `build-manifest.json` 的既有stage，不删除其他目录。重建前先退出该stage的旧exe；文件占用时失败，不强杀用户进程。`build/build-backend.log` 及 `build/pyinstaller-work/mathlens-backend/warn-mathlens-backend.txt` 用于排查冻结遗漏；可选的非Windows模块缺失不等于运行失败。

干净Git构建把对应提交源码ZIP附在backend/source，便于随二进制交付源码；脏工作树测试构建会标 `dirty_source=true`、不生成可能不相符的源码包，不能作为最终发行候选。原生wheel、Python安装器、外壳及题库本身不在项目源码ZIP中；各自许可与来源另保留。AGPL全文取自GNU官方 `https://www.gnu.org/licenses/agpl-3.0.txt`，SHA256：`0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`。

## 冻结 exe 烟测

```powershell
build/desktop-venv/Scripts/python.exe scripts/packaging/smoke_frozen.py
# 可显式指定stage和一个尚不存在的私有输出目录。
build/desktop-venv/Scripts/python.exe scripts/packaging/smoke_frozen.py --stage build/desktop-stage --output '<TEMP私有目录>'
```

脚本复制stage到包含中文与空格的安装路径，使用真实Windows ACL拒写安装树，结束恢复本次deny；临时数据在安装树外。继承DATA/LIBRARY/DIST指向诱饵、DEMO=1，exe只认显式CLI并覆盖本进程。Codex路径不存在，不启动真实Codex会话。子进程PATH只含Windows System32，移除PYTHONPATH/PYTHONHOME，不依赖构建venv或源码导入。

实际运行prepare、serve、health（核对PID/nonce/data_id）、数字PDF上传/切图、扫描PDF RapidOCR/缓存、JPEG/PNG/WebP上传与JPEG归一、SPA深链、题库和tasks；随后stdin shutdown，确认退出0、server.json清理、DB可重命名。输出JSONL、stderr和 `smoke.json`（体积、进程冷启动、各操作耗时、诱饵0项）。冷启动指新进程/新工作区，不清Windows文件缓存，不能作为机械盘或干净VM性能保证。

无管理员测试时使用 `MATHLENS_PACKAGING_OFFLINE_SMOKE=1`：仅冻结入口提供的**收紧**模式，拒绝Python外部socket连接、保留回环给ASGI，关闭ORT遥测；正常桌面启动不设置该变量。该烟测验证冻结模型本地可用，不增加HTTP调试路由，也不放宽任何能力。它不等于系统防火墙封网/无网VM；原生组件的系统级网络隔离仍需干净Windows验收。若不能设置测试ACL，烟测失败而不是冒充只读通过。

不通过源码unittest替代上述真实exe烟测；也不把在开发主机上移除Python路径当作“已在无Python新Windows测试”。无Python/Node/Rust新用户、VC运行库、CPU指令集、SmartScreen、Tauri Job Object及NSIS留给D/最终VM关卡。

## E：从维护库生成发行种子

标注会话在用户批准、备份并完成基础篇导入后，从题库维护副本运行：

```powershell
build/desktop-venv/Scripts/python.exe scripts/packaging/build_seed.py `
  --library '<维护库目录>' `
  --output '<临时目录>/library-seed' `
  --release-id 'zhenti-zhangyu-20261115' `
  --report '<临时目录>/library-seed.report.json'
```

命令以 SQLite `mode=ro` 读取并用 backup API 快照 `library.db`；存在 `library.db-wal/.shm/-journal` 时停止，避免封存半成品。它按 `bank_resources`、来源/目录 JSON 的实际相对引用复制 `bank-assets/**` 与 `knowledge-sources/**`，不复制整目录，并在报告中列出未引用文件数和字节数。源库存在不在 `LIBRARY_TABLES` 白名单内的表、缺失/越界引用时报告后停止，不静默删除或裁剪。构建到同卷 staging，写入真实 release/min-app/library identity/revision/题数/ready/题集及每个文件 hash/size；最后调用 A 的 manifest、文件 hash、SQLite、引用和 ready 计数校验器，成功后才原子发布输出目录。`library.db` 不带 sidecar。`--force` 只允许替换指定输出目录，绝不修改源库。

工具不会扫描或复制个人工作区、题库备份、导航缓存或日志；源库表/行的发行取舍由报告交给协调会话。输出 manifest 和报告不含题目正文。
