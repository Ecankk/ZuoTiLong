# 第三方许可、来源与致谢

项目原创代码和原创文档采用[MIT](LICENSE)。本文件区分软件依赖、共享资料和设计参考；项目MIT许可不替换第三方原有许可，也不授予题目或教材的再分发权。

## 软件依赖

| 项目 | 用途 | 许可与交付方式 |
| --- | --- | --- |
| [PyMuPDF / MuPDF](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) | PDF读取、页面渲染、区域截取 | AGPL-3.0或Artifex商业许可；安装时获取，不在源码包捆绑二进制。项目原创代码的MIT不豁免组合使用/分发时的AGPL义务；没有商业许可时须按AGPL适用条款交付相应源码和许可，不能将整个应用描述为仅受MIT约束。 |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | 本地OCR | Apache-2.0；通过依赖安装，模型及运行时保留各自许可。 |
| [Pillow](https://github.com/python-pillow/Pillow) | 图像处理 | MIT-CMU；通过依赖安装。 |
| [FastAPI](https://github.com/fastapi/fastapi)、[jsonschema](https://github.com/python-jsonschema/jsonschema) | HTTP接口、结果校验 | MIT；通过依赖安装。 |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI服务 | BSD-3-Clause；通过依赖安装。 |
| [python-multipart](https://github.com/Kludex/python-multipart) | 文件上传 | Apache-2.0；通过依赖安装。 |
| [React / ReactDOM / Scheduler](https://github.com/facebook/react) | 前端界面 | MIT；编入dist，许可原文保存在[licenses](licenses/)。 |
| [KaTeX](https://github.com/KaTeX/KaTeX) | 数学公式显示 | MIT；随dist提供，保留[vendor许可证](dist/vendor/katex/LICENSE)。 |
| [Vite](https://github.com/vitejs/vite)、[TypeScript](https://github.com/microsoft/TypeScript) | 前端开发和构建 | 分别为MIT、Apache-2.0；仅开发需要，具体依赖见web/package-lock.json。 |

以上是直接依赖和随包组件的说明；安装得到的传递依赖继续适用其随附许可。Codex CLI由用户自行安装、登录和使用，不随本项目分发，其服务访问和数据处理遵循用户账号适用条款。

## 通用资料

- **考点目录来源**：[hanserdesu/11408Advance-mcp](https://github.com/hanserdesu/11408Advance-mcp)，基于固定版本`22a3e8adfbe9184f4d1c00e2086798342b73bf01`的数学考点进行整理、去重、条件修订与补充。上游MIT许可全文见[保留声明](licenses/11408Advance-mcp-MIT.txt)。附加数学参考的标题、URL、定位与版本见共享目录包内sources；未捆绑其原文、扫描页或教材。
- **题目材料来源**：[lx-ruc/kaoyanshuxue](https://github.com/lx-ruc/kaoyanshuxue)，当前S01适配固定版本`196dc9d2d8271978a030a3721a828c8723cd3864`。题干、答案、解析图片由用户自行获取并导入。未确认内容开放许可，故本项目不随包分发这些原图或原始题库。
- **项目提供的标注索引**：只包含材料散列、规范考点关联、环节及审核出处摘要，不包含题干、答案、推导、原图、个人作答或本机执行记录。项目原创整理适用MIT，第三方来源声明保留；索引不能替代用户自备的题目材料。
- **额外题库**：[cxy-daguan](https://github.com/diamond-pickaxe/cxy-daguan)、[zhangyu-1000t](https://github.com/jlshdsdk/zhangyu-1000t)等目前为调研/适配候选，未纳入首版默认题池或资料包。具体版本与内容许可边界见[题源目录](docs/question-sources.md)。

## 设计参考与感谢

感谢以下项目提供的设计与资料参考。这里区分“借鉴思路”和“已接入题源”，不表示集成了其全部功能或获得其教材内容授权。

| 项目 | 参考价值 |
| --- | --- |
| [error-notebook](https://github.com/Jasmine-Coder-Dev/error-notebook)，以及其注明的[上游项目](https://github.com/SteveSunYifan/error-notebook) | AI错题本、PDF批量录入和结构化结果校验的设计参考。 |
| [kaoyan-quiz](https://github.com/roizenken-design/kaoyan-quiz) | 短测、答案显示和减少复习交互的参考。 |
| [math-question-bank](https://github.com/justcodeit404/math-question-bank) | 题库目录与结构化题目资料的调研参考；其缺失资源未被当作可用题池。 |
| [cuoti-zhiku](https://github.com/whz211417/cuoti-zhiku)、[MathRecall](https://github.com/HSEZCZYW/MathRecall) | 本地错题资料与学习记录组织的参考。 |

当前实现与题源核查见[架构说明](docs/backend-architecture.md)和[题源目录](docs/question-sources.md)。后续直接采用其他项目代码或资源时，应在对应文件与本声明中补齐原作者和许可。
