# 文档目录

按当前问题选择一份文档的相关章节，不按表逐份通读。

| 要查什么 | 维护入口 | 不在这里重复维护 |
| --- | --- | --- |
| 安装、启动与当前能力 | [项目说明](../README.md) | 工具字段、验收流水 |
| 首次配置、资料准备与配置Agent执行步骤 | [配置教程](setup.md) | 第二套安装命令、学习任务字段 |
| 项目提供的纯净资料、版本与第三方许可 | [通用资料](../resources/shared/README.md)、[第三方声明](../THIRD_PARTY_NOTICES.md) | 个人数据、原题正文 |
| 产品应如何工作 | [产品流程](paper-review-workflow.md) | 发布状态、开发待办 |
| 前端信息架构、术语与视觉规范 | [前端设计](frontend-design.md) | 接口字段、产品规则 |
| 新前端读取接口、任务摘要与SSE | [前端接口](frontend-api.md) | 视觉与交互 |
| Agent实际工具与交付契约 | [Agent协议](agent-workflow.md) | 全部产品规则、开发验收 |
| 项目框架、前后端/Agent通信与后端职责 | [项目架构](backend-architecture.md) | 第二份路线图、发布流程 |
| 题源状态与接入 | [题源目录](question-sources.md)、[题源接口](bank-source-interface.md) | 主线任务与全局版本流水 |
| 开发验证怎么选、何时停止 | [开发验收](full-loop-test-checklist.md) | 本次任务完成状态 |
| 需要本人体验时怎么操作 | [人工清单](manual-test-checklist.md) | 默认批准门槛或开发回归 |

应用学习任务的执行步骤由当前`read_skill`及动态schema提供；任务Skill不因普通开发而全部加载。文档描述与实际代码/运行结果不符时，只核对影响本任务的差异，不自动展开全项目审计。

本机若有被Git忽略的`docs/local/`，TODO是任务状态、顺序和用户暂停点的唯一入口；DECISIONS只在相关设计选择需要依据时查阅，题库细项由extra-bank维护。普通开发不要求先读local/README、ROADMAP和全部DECISIONS。

修改信息时更新其维护入口，其他文档使用链接或简短摘要，不复制长规则、计数和验收记录。公开文档不依赖私有文件链接；普通文档修改不另建快照/散列或模拟公开克隆。既有[历史归档](archive/README.md)保留备查，不作为默认上下文或当前任务指令。
