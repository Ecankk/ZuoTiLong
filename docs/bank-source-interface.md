# 题源接入与检索接口

来源、固定版本和实际接入状态只由[题源目录](question-sources.md)维护。本文件维护资料字段、程序检索与Skill更新边界；完整任务协议见[Agent协议](agent-workflow.md)，选题原则见[产品规则](paper-review-workflow.md)。

## 接入与可用状态

资料可以是候选、已完成隔离适配或已导入；这些状态不表示每道题都可用于练习。具体题目须材料可读、身份明确、数学参考已核、原子标注就绪且依赖有效，才进入默认补强池。未标注、失效或争议题仍可浏览/整理。

先用新格式的少量题走通导入、读取和展示，再逐批准备；不因资料数量大就先整库标注。当前哪些来源仍在staging，以题源目录为准，不能凭本地文件存在就调用read_bank。

## 题集与来源

题集是用户可见的分区，也是导入和分发单位，登记在通用库bank_collections：zhenti（真题）、zhangyu-1000（张宇1000题）、other（其他）、example（示例）。来源（S01/S02/S03…）只记录文件出处与版本。每题恰好属于一个题集；一个题集可来自多个来源，一个来源也可拆入多个题集。已有题目不能由新导入改题集，冲突在预演中列出并拒绝写入。选题默认使用全部题集的ready题，真题保护照旧。

## 来源与材料字段

- 固定source_id、revision、source_uid和locator；书籍另存书名、版次、篇章/组别、原题号或页码。未知值留空，不伪造B组或ISBN映射。
- 保留原题文本/图片、答案/解析与规范化展示；资源记录内容散列。文件相同、题目同义、参考一致是不同判断。
- 教辅适用范围与原考试年份/类别分别记录。综合来源的真题须保留可核身份，以执行预留和曝光规则。
- 通用标注引用统一原子ID，记录主/辅/必要前置、方法/环节和材料/目录依赖；个人错因不进入通用标注。
- 同题多来源保留各自出处；条件、题号或结论冲突先待核，不直接覆盖。确认同题不能替代不同参考的核验。
- 第三方正文、PDF和图片留在用户资料目录，不随公开代码分发；具体许可限制见题源目录。

## 导入规范

### 单一流程与标准记录

新增来源统一执行：固定上游版本 → 只读适配器导出 JSONL → 通用覆盖文件补正元数据 → schema/散列校验 → 只读预演 → 对预演摘要明确确认 → 原子写入通用库 → 输出待标注 ID。适配器不写库、不保存人工修正、不自动标注或布置练习。

标准为 `mathlens.bank-record/v1`，UTF-8 JSONL，每行一个来源题目；正文、JSONL 和图片不进入源码仓库。字段如下（字段都存在，未知为 null 或空数组）：

| 字段 | 类型/约束 |
| --- | --- |
| schema | 固定 `mathlens.bank-record/v1` |
| source_id | 来源目录 ID，如 S01/S02；同一批须等于命令的 --source |
| revision | 固定来源版本 string（Git 来源用完整提交 SHA） |
| source_uid | 来源内稳定 string；不以导入次序、数学题号替代原 UID |
| locator | `{path:string,pointer:string,source_sha256:SHA256}`；上游文件、记录定位及文件散列 |
| exam_year/math_type/number | integer 或 null；非真题全为 null，真题身份须三项齐全；不把教辅适用数学类别当考试身份 |
| question_type | `choice`（选择）/`fill`（填空）/`proof`（解答，含计算与证明）/null；未知须列入缺字段报告 |
| max_score | 非负有限 number 或 null |
| stem/answer/analysis | Resource；原题、答案、参考解析分别保存 |
| options | `[{label:string,content:Resource}]`；无选项为空数组 |
| original | `{source_text:string,record:object,sha256:SHA256}`；完整原始来源题目及原始出处文字，sha256 对 canonical JSON(record) 计算 |
| tags | string[]，仅来源导航标签，不表示原子标注或学生错因 |
| math_types | 可选；适用数学类别，[1,2,3]的不重复子集，未知为[]；计入记录与plan散列。真题由身份导出；S03固定版强化篇为[1]（整套为数学一版），既有S03记录由升级迁移确定性回填，不改bank_id与标注；S02无上游值时不猜 |
| book | 可选；`{title,edition,part,chapter,number,locator}`，均为string或null。教辅书名、版次、篇、章及书上原题号；未核的原题号为null，章节内局部序号只放locator |

Resource 为 `{text:string,sha256:SHA256,images:[{path:string,sha256:SHA256,media_type:string}]}`。text 保留文本/Markdown/LaTeX，散列为其 UTF-8 字节 SHA256（空文本亦有散列）。图片路径相对 `--asset-root`（默认 JSONL 所在目录），禁止绝对路径、父目录穿越和指向根外的符号链接；散列按真实文件字节计算。选项连同题干规范化组合后供显示，原文和分角色资源仍保留，不能丢选项。无题图可正常入库；缺题干（无文字且无图）为校验错误，缺答案/解析/题型/分值为报告项，不编造补齐。

canonical JSON：UTF-8，sort_keys=true，ensure_ascii=false，分隔符 `,`/`:`，禁止 NaN/Infinity。具体机器约束由 app/bank 下版本化 schema 维护，接口和适配器共用校验。

当前支持 PNG/JPEG/WebP。每个角色的多张原图均校验并按内容散列保存；为兼容单图片读取/练习快照接口，另存按顺序纵向拼接的显示衍生图，不替换原件。文本与图可并存，客户端应组合 `question_text`/`question_image`；纯文本不生成图片。来源原始记录和历史版本独立保留，显示规范化不改变出处。

### 适配器与覆盖文件

适配器放在 `scripts/bank_source_adapters/`，只读取指定上游文件并转换为标准记录。固定来源版本和输入文件 SHA256 一并输出；上游结构异常须失败，不能静默丢题。适配器可按来源文字提取考试身份，但不得按通用题号区间猜题型、分值，也不得按已知正确答案补题干。

统一转换命令：

```text
python scripts/adapt_bank_source.py --adapter cxy-daguan --root <来源根目录> --output <临时目录/records.jsonl>
```

首个范围是固定 7e79423253454dfb32246b6a84c7d6fd6efaa5b8 的 cxy-daguan 中 2026 数一候选。22 条明确题号与未标题号的重复候选都保留为导出记录；无法确定身份的记录保留 null，不能猜配。其他来源复用相同命令与标准，只新增适配器。

适配器模块通过目录发现（文件名下划线对应命令中的连字符），实现 `adapt(root, *, year=None, math_type=None)`，返回标准记录列表；不适用的筛选须明确拒绝，不得静默换范围。当前 cxy 适配器仅接受本批已检查的 2026 数一范围，模拟卷标签不作为原考试身份。覆盖文件为 `scripts/bank_source_adapters/cxy_daguan_2026_math1.overrides.json`；题型/分值依据原卷印刷部分，3 条未编号候选明确排除待核。

人工补正使用 `mathlens.bank-overrides/v1` JSON 文件，跟适配器版本管理，只有元数据，不含正文：

```text
{schema,source_id,revision,entries:[
  {match:{source_uid:string} 或 {exam_year:integer,math_type:integer,number:integer},
   set:{question_type?,max_score?,exam_year?,math_type?,number?,exclude?:boolean},
   reason:string,evidence:string}
]}
```

reason/evidence 必须非空，注明原卷页码、核验依据或用户明确给定范围。仅允许上表 set 字段，不能覆盖题干、答案、解析、出处、来源 UID 或散列。重叠规则对同字段给不同值时报错；未匹配规则也报错，防止覆盖错版本。预演逐项列出 source_uid、字段、原值、新值及依据。exclude=true 仅排除待核/重复候选，不删除已入库记录；仍列入报告。2026 卷的题型、分值分布属于该卷的覆盖数据，不硬编码在 cxy 适配器中；解答题分值未核实时保留 null。

### 唯一标准导入入口与预演

```text
python scripts/agent_tasks.py import-source --source S02 --collection zhenti --input <records.jsonl> --overrides <overrides.json> --asset-root <来源根目录> --dry-run
python scripts/agent_tasks.py import-source --source S02 --collection zhenti --input <records.jsonl> --overrides <overrides.json> --asset-root <来源根目录> --confirm <plan_sha256>
```

`--collection`必填，题集ID计入plan_sha256。S03强化篇的适配器为`zhangyu-html`（固定revision与37个输入文件散列见scripts/bank_source_adapters/zhangyu_html.hashes.json），导入题集zhangyu-1000。共享题目标注索引包为`mathlens.question-index/v2`，条目带受散列保护的collection_id，可按题集导出、预览和导入；v1包仍可导入。操作前备份目标库，并在该进程显式设置 `MATHLENS_DATA_DIR`（目标工作区）与 `MATHLENS_LIBRARY_DIR`（目标通用库）；开发实跑只指向 TEMP 副本。转换器默认不覆盖已有 JSONL。导入命令可用 `--report <私有路径/report.json>` 另存报告；确认须使用本次预演给出的完整摘要，库有变化即重新预演。入口只初始化/写入通用库，不迁移个人工作区。正式主库导入及待标注 ID 的交接由标注会话在备份后执行。

没有 --confirm 时只预演；--dry-run 不初始化工作区、不创建数据库、不复制图片、不写学习记录。所有记录、覆盖、文本/图片及原始记录散列先校验。提供 --confirm 后重读并校验；确认摘要须与当前输入、覆盖、相关库记录和身份重叠一致，否则拒绝，须重新预演，不沿用旧确认。写入只涉及通用库，已有工作区的标注、阅读笔记、作答、曝光不删除。

预演报告为 JSON：`plan_sha256`、`source_id`、`revision`、`added/updated/unchanged` 的稳定 bank_id 列表、`missing_fields`、`identity_conflicts`、`duplicate_candidates`、`excluded`、`overrides_applied`、`needs_annotation`。散列/schema/路径错误导致整体拒绝。写入报告另有 `applied`；报告保留在临时/私有目录，不把正文写进控制台报告或版本库。

bank_id 由 source_id 和 source_uid 的 SHA256 稳定生成，不含 revision；同来源重导入不新增身份。库内保存当前标准记录和不可变来源版本历史。相同记录完全不更新既有题目、资源或标注；材料更新保留旧版本和资源，旧标注自然按既有材料依赖失效，旧练习继续读已固定快照。来源字段更新不清空人工 fingerprint、notes、bank_views、bank_exposures 或作答；新导入不能证明数学结论正确。待标注列表用于交接，不自动启动学习任务。

### 考试身份、重复与冲突

考试身份是 `(exam_year,math_type,number)`，独立于来源 URL、来源 ID 和题图有无。原卷先使用已保存的固定参考绑定；否则以年份/类别/题号检索所有来源，顺序固定为 source_id、source_uid、bank_id 升序（旧 S01 按 S01 计），不按导入先后变更优先级。题型/分值存在明确冲突时不任意选择，相关显示值返回 null；候选仍全部提供，须后续核对。缺失值可由该身份其他无冲突的已知来源补充，不猜值。排序只选出处导航，不证明数学同题或参考一致。

同身份跨来源重叠、同批同身份多 UID、题干+选项相同的多记录均列为冲突/重复候选，不自动覆盖、删题、写 bank_links 或复用标注。明确确认预演允许保存这些候选，但不会把它们标成 ready。部分身份（例如有年份/类别却无题号）只作为候选，不进入完整考试身份匹配。

预留、同类别遮挡、已看题/解析和作答暴露按完整考试身份保守联动，即使另一来源后来才导入也不能绕过。保护联动不等于数学 aliases：通用标注的同题/参考核验仍沿原确认流程，不能因身份文字相同合并结论。

`read_bank` 支持纯文本/LaTeX，返回 `text` 或按角色的 `resources`，内部读取不产生学生曝光。练习读取返回 `question_text`，保留遮挡、作答后查看解析和固定旧材料规则。题库列表不内联答案/解析；纯文本角色使用既有 `GET /api/bank/{id}/{question|analysis|answer}`（可用 `view=library` 自主浏览），返回 `application/json` 的 `{bank_id,role,text,sha256}`，实际公开读取沿原路径登记看题/解析曝光。图片角色维持图片响应；文本/图片响应均不绕过练习快照。旧练习界面的纯文本 fallback 已存在；旧题库界面可显示 `stem`，其解析区仅支持图片，后续新前端需读取上述文本角色接口。

### S01 兼容边界

现有 `import-bank` 暂保留兼容流程：它还负责解码像素身份、人工题源导航修正保留及旧路径材料版本。强行替换会影响已有标注/固定材料散列，本批不自动迁移旧 S01、不换旧 bank_id。标准 Resource 支持 S01 的纯图片题和答案/解析组合；新入口以图片回归验证同一记录重导入不改题目、资源、标注。旧 S01 重导入仍须通过原有保留测试。

后续将 S01 适配到统一入口前，须单独核对旧 bank_id 和固定路径/像素散列的迁移，不能把来源重叠当迁移许可。这是现存入口兼容，不为新来源新增导入分支。

## 学习检索与读取

read_skill({name:"bank-search"})从磁盘返回当前Skill、source_catalog和source_interface及其版本信息；不把全库题号、计数或本机路径复制进Skill。新增同格式资料不需要新学习会话。

| 入口 | 当前作用 |
| --- | --- |
| catalog({topic_ids,stages,methods,offset,limit,include_history}) | 原子/子树的就绪题召回；默认过滤预留、已做/看解析及待做重复，沿原probe返回已有练习 |
| catalog不带topic_ids | 题源、章节、年份等导航；粗标签不是数学标注 |
| GET /api/bank/search | topic_id、stage、method使用重复查询参数，分页前过滤；只回身份/访问/历史元数据 |
| read_bank({bank_id,role,probe_id}) | 实际读题与参考并登记材料版本；已有练习沿固定材料，查询候选不算已读 |
| task_context | 本任务的目录定义、来源、标注基线或知识证据；具体作用域见任务schema |

数学一/二/三共同检索，不设配额或优先级。methods目前是已有完整文字的精确过滤：先原子召回，必要时复制已有方法值收窄；无命中先去掉可选方法/环节过滤。程序处理确定性筛选，Agent实际读题后判断本次训练价值。

## 浏览与选题分开

GET /api/knowledge/links/summary提供节点计数；links通过view=completed/bank、topic_id、scope和分页反查。GET /api/bank/{bank_id}/topics及批量/api/bank/topics正查原子标签。

浏览保留已做、预留和待核来源，不套用选题过滤。只返回标签、角色、出处和状态，不在列表中回传解法或增加曝光。标注就绪、个人完成和本轮是否值得选用分别判断。

## 更新时维护哪里

| 变化 | 更新内容 | Skill |
| --- | --- | --- |
| 同格式增题 | 资料、索引及来源覆盖记录 | 通常不改 |
| 新题源/版次 | 来源目录、题号映射和适配器，验证代表题 | 接口不变时通常不改 |
| 题目/参考纠错 | 保留原件和版本，处理受影响标注 | 教学方法不变时不改 |
| 目录/标注规则变化 | 独立维护目录、依赖及受影响题 | 方法或契约确实改变时同步 |
| 资源格式/工具字段变化 | 适配器、工具、校验、展示和接口文档 | 影响Agent调用时同步 |

资料更新不自动追加作业，也不替换已布置题。检索前置、阶段调度、交付schema由Agent协议维护，不在各适配器或通用Skill中复制一套流程。
