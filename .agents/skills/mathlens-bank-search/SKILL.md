---
name: mathlens-bank-search
description: 为 MathLens 本卷合并后的补强目标，从统一本地题池阅读并筛选少量有价值的练习，核对历史重复、实际解法和来源版本。
---

# 按目标检索补强题

这是应用在原卷分析完整核对、保存回执且远端结束后派发，或用户追加的独立 prepare_practice 任务。先读 context.learning_task 的输入、result_schema 和已有练习；不重分析整卷、不要求学生确认错因或管理计划。用 apply_report 的 `{result:完整任务封装}` 交付，取得保存回执后结束当前阶段。

当前read_skill返回knowledge_catalog与catalog_policy。topic_ids只引用现有稳定ID，已有别名对应同一ID；训练目标和方法/操作另记，不将goal.id或表现句当知识节点。本轮不新增、改名、合并目录，未覆盖内容写入limitations；由独立目录维护集中核对，后续知识证据整理也不负责自动建点。

## 明确要检验什么

结合本卷原题考点、首错环节、可能原因和历史作答，合并有相同操作缺口的原题。同考点但缺口不同不强行合并；原因未知仍可按必要操作复习，不把假设写成确定弱点。目标应能说明“需要学生完成哪一步、这一表现能说明什么”，而非堆叠章节标签。

每重点目标默认1～2道是预算，可为0。能同时覆盖多个目标的题只布置一次；已有改善时不机械追加。检索前看历史原卷、已选/未做/已做练习和有效阅读笔记，优先复用合适记录。追加优先检查仍未覆盖且值得检验的环节，不对已有合适题目的目标重复整轮检索；材料变化或明确的间隔复习目的另行处理。

## 读取当前题池

每次 read_skill(bank-search) 返回 source_catalog 和 source_interface，分别来自 `docs/question-sources.md`、`docs/bank-source-interface.md`。只有 catalog 实际可访问的条目可选；潜在来源、staging文件和README声明不等于已接入。普通扩库更新来源/索引；工具格式或教学规则改变才更新Skill，不每批数据重写流程或新建会话。

先用`catalog({topic_ids:[实际稳定ID],offset:0,limit:30})`查询已就绪标注，再按实际目标选择是否添加stages。methods当前按完整文字精确匹配，并非规范方法ID或同义检索；仅从已召回条目的methods原样取值用于收窄，不能用自编简称首搜。加入方法/环节后无命中，应先去掉这两个可选过滤核对原子候选，再判断缺口。

原子或上位目录ID会查询完整子树；仅材料、数学/原子标注及依赖有效的ready题参加召回，确认同题合并，任一确认别名预留时整组排除。未知ID先核对目录，不编造名称或用goal.id替代。再read_bank实际阅读原题、必要图和参考内容，判断与目标是否契合；程序召回不代替数学适配与练习价值判断。

任务为1.9时，先用practice_knowledge.question_mappings定位原卷的已核原子，再用task_context的knowledge_query/topic_ids定位并读取捕获定义。catalog只召回本任务捕获的有效标注；新题须保留其annotation_id，并用read_bank的role=all核对材料和已核通用解法。可复用已有推导，但仍要确认实际条件与本次回答范围；不回退来源粗标签或猜标注ID。

items默认排除已有待做练习、已作答或看过解析的同题。existing_exercises给出原probe_id及can_reuse：核对本任务historical_exercises/retained_exercises和当前材料后复用，过期来源先复核，不能复制一题绕过。确有间隔复习目的时才用include_history=true检索做过或看过解析的题，保留其history并在repeat_reason写清目的；不能据看过答案后的完成新增独立成功。

数学一/二/三只是出处和显示保护元数据，不按类别分库、设优先级或配额，不按书名中的“数一”排除题目。 student_access.can_view和analysis_allowed是学生网页权限，不能作为Agent内部可读/可选条件；未预留的就绪题即使对学生隐藏，仍可内部read_bank核对并选用，网页再等待学生确认。不得把模糊保护解释为候选不可用。顺序是稳定浏览顺序，不是推荐排名；跟随next_offset分页，说明实际查询与阅读范围。未命中只表示当前就绪标注无相符题，可扩展相关原子/上位目录或必要前置，不能宣称原始全库没有。旧topics/years/exclude_years/bank_id导航用于资料定位；未标注或待核条目不能被当作已准备好的新增练习，缺口如实写入limitations，不把校库任务交给学生。

目录粗分类和已有指纹文字只是导航，同义词用于定位同一规范ID。没有一题覆盖全部要求时，可选真正有用的关键步骤/前置练习，明确覆盖与未覆盖的部分，例如只检验建模或积分限设置。不能改条件、忽略必要图或把不同模型当成同题；确实无高价值候选就留空并说明覆盖边界。

## 复用、去重与追加

结合条件、目标、解法和操作指纹，实际阅读识别同题、跨来源重复和低价值换数，不以文字相似度/粗标签替代数学判断。review_cross 的 other_id、distinct=false 可记录确已核对的同题，但不是展示其他类别题目的前置关卡；同题关联不改变类别显示设置。

按本任务schema工作：

- 支持 retained_exercises 时，用原 probe_id/goal_ids 保留本卷练习，满足 required_retained_probe_ids；exercises 只含新增题，goals 覆盖保留和新增目标。分析改变后，先重新 read_bank 核对拟恢复旧题；未保留的旧作答仍在，不直接重新开放过期安排。
- 仅在schema支持 related_probe_ids 时，引用 historical_exercises 中 can_reuse=true 的跨卷练习，先读当前题干/解析并核对原回答范围是否适合新目标。沿用原 probe_id，不复制题/照片/作答/曝光。一个原记录可服务多个目标；来源卷过期/归档/停用不能冒称可继续。已有练习不能只在reason中提及而没有结构引用。
- 新增题不重复布置已有未作答同题；已有作答的题确需间隔复习时，repeat_reason 写明目的，保留旧证据。已反馈不等于整个考点掌握，不应仅引用旧答对记录充当本次新检验。

1.9保留/跨卷引用必须用read_bank({bank_id,probe_id,role:"all"})核对原练习固定版本。工具仅在原选题题图凭据一致且标注就绪时升级旧练习；读取本身不改作答，成功交付才保存绑定。凭据/材料不足或标注未就绪时如实记录限制，不能改用当前库另一版、复制题或要求学生校标签；旧任务仍按自身schema读取。

任务列出legacy_review时，其中无法证明原版本的旧题由系统保存为待核历史，不在required_retained_probe_ids中强制保留。本轮可以继续其他就绪题，不把这些旧题强塞入retained_exercises或假称可跨卷继续；原作答/反馈保留，不要求学生修数据。
- 无新增可交空 exercises，但保留必要旧题和目标，limitations 写实际阅读范围、未覆盖内容及取舍。不能把“未继续查阅”写成“全库没有”。旧schema没有的新字段不添加。

按 mathlens-probe-design 定义回答范围与选择理由。题目/条件/图/解析发生变化时重新阅读；memory_write 的 `bank/<bank_id>.json` 笔记保留来源版本、材料散列、核对范围和未决点。路径或散列清单不代表已读/数学审定。

共享题目标注索引若已明确导入，只证明与本地材料匹配的原子/环节及来源声明；prepared_question会标明cache_provenance，可能不含reference_reasoning。它不是本机独立解题回执，不能凭ready省略本次读题/参考和数学适配判断；索引被停用或材料/定义不符时不用于新选题。

## 展示边界

本地题库可直接浏览；针对性练习以 student_access 为准，当前备考类别在开启隐藏时需用户确认，其他类别直接显示。目标可说明原卷已暴露的薄弱点，但未确认候选只给类别/年份/题号，不能在目标、limitations、选择理由或最终回复中泄露其特有条件、题干或答案。答案/解析另按网页操作开放，不代替学生确认，不把阅读记为成功。

S02/S03接入前不选staging条目；接通新的章节/电子题干/选项/公式/必要图/解析或版本接口时，与source_interface一起更新导航说明，仍复用同一教学流程。
