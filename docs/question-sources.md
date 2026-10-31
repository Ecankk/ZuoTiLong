# 题目来源目录

目录更新时间：2026-10-31；各来源证据核查日期以条目中的固定版本和记录为准。本文件维护当前可接入来源与潜在来源，是题源状态的统一入口；旧审查文档保留当时版本和结果，不代替本目录。仅登记公开来源和通用接入信息，不记录用户的试卷、成绩、作答或本机路径。

“已接通”表示存在导入适配，不表示所有新安装都自带题目。“文件已检查”“内容已抽检”“数学结论已核对”分别记录；有题干、解析字段或文件散列，均不能直接证明答案正确。下列记录数不是精校独立题数。

项目随源码提供的[通用资料包](../resources/shared/README.md)只有考点目录与不含正文的标注索引；原始题干、答案和解析由用户自行取得并导入本机通用资料库。来源许可和设计参考分别见[第三方声明](../THIRD_PARTY_NOTICES.md)，项目代码的MIT许可不覆盖第三方题目内容。

题目来源与考点目录来源分开登记。应用当前版本和全局功能边界见[项目 README](../README.md)。`mathlens.knowledge-source/v1` 考点来源包用于目录维护；六条多元微分考点候选使用 PKU、OpenStax、MIT 的固定原文资料，并已通过 `maintain_catalog` 工作流保存完成。这是目录维护证据，不是题目资料导入，不计入下方题库题数，也不改变 S02/S03 的 staging 状态。

## 已接通的来源

| ID | 来源 | 已核查内容 | 当前接入与边界 |
| --- | --- | --- | --- |
| S01 | [lx-ruc/kaoyanshuxue](https://github.com/lx-ruc/kaoyanshuxue/tree/196dc9d2d8271978a030a3721a828c8723cd3864) | 2009–2025 数一、数二、数三，各 386 条记录；题图、解析图、分值、年份、题号及考点元数据。跨类别可能重题，1158 条不等于 1158 道独立题。 | 支持从用户本地目录 `import-bank`，资源复制到本机通用资料库；重导入保留阅读笔记、作答与曝光。数一历史检查中 2024 Q19 无独立答案图，但有解析图。未完成全库数学审定。根目录未见内容开放许可，资料不随项目捆绑。 |

## 优先适配的非真题资料

以下来源尚未导入应用；“优先”是接入建议，不是当前页面已具备这些题目。

| ID | 来源 / 固定版本 | 实际文件核查 | 适配价值与未决事项 |
| --- | --- | --- | --- |
| S02 | [diamond-pickaxe/cxy-daguan](https://github.com/diamond-pickaxe/cxy-daguan/tree/7e79423253454dfb32246b6a84c7d6fd6efaa5b8) | `library/bundled-library.json` 有 7,083 个唯一 UID，均有电子题干、答案和文字解析。907 条记录引用图片，共 1,641 次引用、1,639 个唯一资源；对应文件均存在且 SHA256 与声明一致。 | 独立 JSONL staging 与本地来源/章节索引已完成，仍未导入应用。当前只分 4,274 道练习题、2,809 道真题候选；练习题由原始 4,230 道明确适用范围记录加 44 道未标适用范围但内容完整的记录组成。46 个来源标签互有重叠，不代表书目独立题量。真题与教辅混合；UID 2314 同时有 1987 数一、李林 880、武忠祥严选三项来源主张，关系待核，可能包含教材转载，尚无证据证明它们互斥。代码 MIT 不覆盖第三方题库内容；上游声明权利归原权利人，不随应用分发。 |
| S03 | [jlshdsdk/zhangyu-1000t](https://github.com/jlshdsdk/zhangyu-1000t/tree/19f626daefe25fe0e0d76abc30413b697fe4ce24) | 仓库自称“2026张宇考研数学1000题刷题版”。逐文件读取 71 个章节 HTML、1,307 个题目块：基础 536、强化 683、综合 88；强化篇 chapter-32 至 chapter-67，覆盖数一高数、线代、概率。683 道均有电子题干与解析区，原始题型均保存在 `upstream.question_type`：填空 172、选择 222、解答 289。394 道有单列答案，另 289 道为解答题，答案需从解析中核验；未发现题图。 | 用户指定的 B 组按强化篇处理。强化篇 HTML 未标 B 组、ISBN、页码或原书题号，故不得冒称与某个印次逐题对应。新华书店书目列有 2026 年同名《考研数学题源探析经典1000题》（ISBN 9787576308181），但书目存在不能证明该 HTML 与该 ISBN 内容一致。独立适配器已导出 683 道 staging JSONL，未导入应用；未来统一读取/导入时需将 `upstream.question_type` 归一化为通用题型字段；未见教材内容开放许可。 |
| S04 | [Alex-qiaolezi/lilin880-study-checkin](https://github.com/Alex-qiaolezi/lilin880-study-checkin/tree/2910b2b5ed3cc2bd93474caaee9cb966c2a063d7) | `data/questions.json` 有 803 条索引，高数 541、线代 262；其元数据明确排除证明题、拓展题。827 条题图引用均唯一且文件存在；原始高数/线代做题本 PDF 分别 647 页、311 页。元数据称来源为“李林880数二”，不含 ISBN/印次；无概率题。 | 仅有题号、章节、页码和题图，没有电子题干、答案或解析卷；不完整覆盖 880。索引与 PDF 可用于图像候选，不足以作为已核验练习直接导入。公开书目列有 2027 数学二版（ISBN 9787512446823），但无法据仓库元数据将本地材料匹配到该印次。未见内容开放许可。 |

S02 的来源字段可匹配“严选”115 条、“武忠祥”103 条、“1k”643 条、“0.88k”960 条；这些是全库 7,083 个 UID 上的可重叠来源匹配数，不是互斥作者统计或已确认的书目覆盖量。4,230+44 与 4,274 是旧筛选集和当前两类索引的口径关系，没有新增或丢失题目；44 条仍缺少上游适用数学类别。来源/版次未核、资源完整性和数学未核分别记录。S02/S03 的样题与来源核对原文见本机可选路径 `docs/local/extra-bank/archive/2026-10-27/README.md`；两者仍为 staging，尚未进入 MathLens `catalog/read_bank`。

应用当前版本和全局功能边界见[项目 README](../README.md)，题源接口与接入边界见[题源接口说明](bank-source-interface.md)；题库专项状态的本机可选路径为 `docs/local/extra-bank/STATUS.md`。目录维护与题目标注使用独立 1.7 工作流和契约；正式目录数量以 `GET /api/knowledge/catalog/summary` 为准，本目录不固定滚动节点总数。`catalog` 支持按已发布原子标注检索就绪题目及子树；S02/S03 仍为本地 staging，尚未进入 MathLens `catalog/read_bank`。本轮数一、数二、数三代表题已完成统一复标、召回及独立数学核查；当前有效性以目录依赖校验为准。应用已支持通用目录包及独立题目标注索引的预览、明确接受、导入和导出；包不含题库正文、解法、个人资料或伪造的本机AI回执。须与本地材料及定义依赖匹配才可复用，不自动附送题库或证明全库数学正确；专项不改个人库。

代表文件：[S02 结构化快照](https://github.com/diamond-pickaxe/cxy-daguan/blob/7e79423253454dfb32246b6a84c7d6fd6efaa5b8/library/bundled-library.json)、[S02 第三方声明](https://github.com/diamond-pickaxe/cxy-daguan/blob/7e79423253454dfb32246b6a84c7d6fd6efaa5b8/THIRD_PARTY_NOTICES.md)、[S03 强化篇第一单元](https://github.com/jlshdsdk/zhangyu-1000t/blob/19f626daefe25fe0e0d76abc30413b697fe4ce24/chapters/chapter-32.html)、[S04 题目索引](https://github.com/Alex-qiaolezi/lilin880-study-checkin/blob/2910b2b5ed3cc2bd93474caaee9cb966c2a063d7/data/questions.json)、[2026 张宇书目](https://item.xhsd.com/items/110000104704141)、[2027 李林数二书目](https://hotbook.nbt.edu.cn/nbt/?id=168542&what=detail)。

## 武忠祥及其他备选资料

| ID | 来源 | 实际核查范围 | 当前判断 |
| --- | --- | --- | --- |
| S05 | [zhangrun-HIT/24-](https://github.com/zhangrun-HIT/24-/tree/39942739e4960a25ecd96ccb3aba87fc48370c5c) | 24考研武忠祥课程包答案；2048 张图片，大量按节排列的基础过关/真题测试 PDF；实际读取并渲染 1-1 手写版 PDF。 | 抽检为 iPad 作答及批改截图，题干、解答混排。可补充练习材料，但不是可直接导入的标准严选解析库；需切题、OCR 和解答核对。 |
| S06 | [SyHang-hash/408----- 的武忠祥严选题](https://github.com/SyHang-hash/408-----/tree/f446c4d46e5992ff677a8118eaaeb2e4409df9d4/%E6%AD%A6%E5%BF%A0%E7%A5%A5%E4%B8%A5%E9%80%89%E9%A2%98) | 已冻结 revision `f446c4d46e5992ff677a8118eaaeb2e4409df9d4`。9 份文件自称 27 考研《高等数学基础篇》严选题，覆盖 1–12 章；共 99 页、80,582,497 字节。第 1–5 章两份有可提取文本；第 6–12 章七份共 56 页，文本层合计仅 758 字，已渲染第 6 章首页和后续页样本。 | 可以对应到公开书目中的 2027 高数基础篇（ISBN 9787109323070），但仓库文件无法确认为该 ISBN 的同版扫描。主要是扫描/手写讲解、多题同页；手写解答未经权威校核。适合用户本地查阅，不适合直接导入；未见明确内容开放许可。 |
| S07 | [justcodeit404/math-question-bank](https://github.com/justcodeit404/math-question-bank/tree/0a4486ffaf140e3185f382858709e32ab84e996a) | 1000题 901条/48章、880题 927条/12章、660题 660条/11章，包含真实电子题干、选项、章节和页码；前三库偏数二。 | 三库答案/解析正文为空，`answer_ref` 所指图片未随仓库提交，题图也缺失。880 样本有 OCR 条件缺损。适合作为用户补齐本地原件后的候选索引；1000题没有可确认的B组标记。根目录未见 LICENSE，README 声明个人学习。 |
| S08 | [sikouhjw/zhangyu1000](https://github.com/sikouhjw/zhangyu1000) | 2020数一 LaTeX 重排；检查 67 个章节文件，计 1137 个题目环境，没有发现解答文件或 B组标记。 | 可以避免题干 OCR，但版本旧、按主题重排，需补原题号映射和解答。LPPL-1.3c 不能单独证明原书内容再分发授权；正式接入前补记 SHA。 |
| S09 | [TsekaLuk/Kaoyan-Math1-Papers](https://github.com/TsekaLuk/Kaoyan-Math1-Papers/tree/3151b4acf26ea19ccd427b869a715e65e1990091) | 历史检查：顶层 40 份年份 Markdown，38 个不同年份；有题干、LaTeX、答案解析样本。31 处图片相对路径失效，克隆内有同名候选文件。 | 可补真题文字检索和图文交叉核对；需修复图片映射并防同名误配，不能直接用转录覆盖原图。仓库标 CC BY-NC-SA 4.0。尚无应用适配器。 |
| S10 | [fjw345/mathonline](https://github.com/fjw345/mathonline) | 先前仅查 README，声明含考研数学题并排除部分缺图/答案待确认题。 | 仅候选，尚未完成真实数据核对、冻结版本或接入。不能以 README 数量充当本库覆盖率。 |
| S11 | [YLXDXX/AM601-kaoyan](https://github.com/YLXDXX/AM601-kaoyan) | 先前仅在线查看：国科大601高等数学甲 LaTeX 真题，部分年份有参考答案。 | 自主命题，可后续筛选方法训练；不能直接归为全国统考数一/二/三。未接入。 |

[MathRecall](https://github.com/HSEZCZYW/MathRecall) 提供错题系统代码，但题库需用户自行放到私有目录；它属于产品参考，不作为新增题源统计。AI错题本、kaoyan-quiz 等也应与题源分开登记。

## 接入规则

身份/版次、材料、逐题就绪和Skill维护统一见[题源接口](bank-source-interface.md)。本页只登记具体来源及核查证据，不重复学习流程或开发验收。

## 后续更新

新增来源先登记链接、检查日期、固定版本、代表文件、实际核查范围、资源缺口和接入状态；有新证据再修改“候选/已适配”。上游更新后检查内容散列，旧阅读笔记不能自动视为仍有效。

详细历史证据见 [早期资料库比较](archive/2026-10-25/question-bank-options.md)、[参考源码审查](archive/2026-10-25/reference-source-review.md) 和相应 JSON 审查快照。开发优先级及个人验收记录维护在被 Git 忽略的 `docs/local/`。
