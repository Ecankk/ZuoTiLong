# 新前端资源接口契约（B3）

本批提供按资源读取、任务摘要、SSE 和后台按需自动连接。旧接口继续可用。首页规则、画像图表、反馈已读、partial 批改和逐步对照契约不在本批。

## 公共规则

- 同源 `/api`；标识为不透明 string，时间为 ISO string，缺失值为 null；下文 `?` 表示字段可缺省。对象内的 ID 不用于推断年份、题型或状态。
- 新增分页接口使用 `offset: integer >=0 =0`、`limit: integer 1..100 =20`，返回 `Page<T>={items:T[],total:integer,offset:integer,limit:integer,next_offset:integer|null}`。顺序由后端固定，并以 ID 消除并列。
- `GET /api/papers`、`GET /api/bank` 仅在提供 offset 或 limit（bank 也可提供 topic_id）时采用新分页响应；不提供这些参数时保留旧响应及行为。
- 新资源 JSON GET 返回强 ETag（序列化响应的 SHA256）；`If-None-Match` 接受单值、列表、弱标签或 `*`，匹配返回 304、空响应体。校验访问权限、资源存在性和参数在条件请求之前执行。`Cache-Control: private, no-cache`；错误、SSE、旧接口维持 no-store。ETag 不等于 SQLite data_version。
- 查询结果、遮挡或暴露状态变化会改变 ETag；无变化可复用。前端使用 query key（资源 ID + 所有筛选参数），mutation 成功后立即失效相应 key；SSE 另通知外部变更。图片沿用旧资源入口与暴露记录，不应用上述 JSON 条件请求规则。
- 错误为 `{error:string}`：400 参数/业务校验失败；403 非本地/跨源请求或材料不可访问；404 资源不存在；409 原任务/材料状态冲突。不可用的学习服务通过任务摘要的 agent_unavailable 表达，保存的数据仍可读。

## 试卷与逐题分析

`Counts={correct:integer,wrong:integer,partial:integer,unknown:integer,total:integer}`。

`Paper={id:string,title:string,exam_date:string|null,score:number|null,total_score:number,score_confirmed:boolean,archived_at:string|null,created_at:string,updated_at:string|null,analysis_status:string,counts:Counts}`。
score 仅返回已核定值，未核定为 null；analysis_status 沿用保存的 import_status（needs_review/processing/diagnosed/partial_analysis 等），不是完成百分比。

`QuestionSummary={id:string,paper_id:string,number:string,question_type:string|null,max_score:number|null,score_earned:number|null,correctness:'correct'|'wrong'|'partial'|'unknown',review_state:string,analysis_available:boolean,matched_bank_id:string|null}`。
题型和 max_score 只取匹配题库的已保存 metadata（question_type、score/max_score）；S01 导入器保存的 source_url=https://github.com/lx-ruc/kaoyanshuxue 的数值 type 按源枚举 1=选择题、2=填空题、3=解答题适配，其他来源不套用此映射。优先使用当前报告的固定来源绑定，再使用唯一的 S01 年份/类别/题号出处匹配。歧义、未知编码或没有字段均返回 null，不用题号规则猜题型/分值。出处定位不表示数学等价或题库标注就绪。题库缺字段不改写原报告。

| 方法/路径 | 参数 | 响应 |
| --- | --- | --- |
| GET /api/papers | archived:'0'/'1'/'all'='0'；分页参数 | Page<Paper>；日期、创建时间、ID 倒序 |
| GET /api/papers/{paper_id} | 无 | `{paper:Paper,analysis:AnalysisState,weak_topics:TopicRef[],practice_counts:PracticeCounts,summary_status:'missing'|'available',actions:string[]}` |
| GET /api/papers/{paper_id}/questions | 无 | `{items:QuestionSummary[],total:integer}`；数字题号优先升序，其余按保存题号/ID；整卷无分页 |
| GET /api/questions/{question_id} | 无 | `{question:QuestionSummary & {stem:string,regions:Region[]},diagnosis:Diagnosis|null,topics:TopicRef[],evidence_urls:string[],evidence_regions:EvidenceRegion[],practice_counts:PracticeCounts,previous_id:string|null,next_id:string|null,capabilities:{step_comparison:false}}` |
| GET /api/papers/{paper_id}/summary | 无 | `{status:'missing'|'available',result_id:string|null,created_at:string|null,summary:object|null}`；summary 为已保存 summarize_paper.result（overview、key_findings、improvements、next_actions、limitations、source_refs），不生成新总结 |

`AnalysisState={report_id:string|null,completion:string|null,review_status:string|null,summary:string,limitations:string[]}`。`TopicRef={topic_id:string,name:string}`。
Region 为现有 `{page:integer,bbox:number[4],role:string}`（PDF 点坐标）；evidence_urls 使用现有 `/api/questions/{id}/evidence?region=N`。`EvidenceRegion={region_index,page,bbox,image_url,image_width,image_height,image_origin:[x,y],scale:2}`，宽高与整数原点来自与 /evidence 相同的实际渲染图（含像素取整）；图内点击距顶部 d 个 CSS 像素、图片内容显示高度 H 时，PDF y=(image_origin[1]+d*image_height/H)/scale，不要用 bbox 高度猜比例。原 PDF 缺失时为空数组。
Diagnosis 为现有 present_diagnosis 的逐题对象：stem、observation、correctness、answer_evidence（student_work/student_state/marking/marking_note）、correct_parts、first_error、solution_guide、reference_answer/reference_reasoning、hypotheses、cause_summary、knowledge、fingerprint、regions 等已保存字段；旧报告缺字段保持兼容，不伪造步骤。
TopicRef 只来自有效知识映射；weak_topics 是已关联且 state=需要关注 的考点，不根据字符串造 ID。

## 练习

`PracticeCounts={pending:integer,grading:integer,graded:integer,needs_supplement:integer,inactive:integer,total:integer}`。
`PracticeStatus='pending'|'grading'|'graded'|'needs_supplement'|'inactive'`。失效计划、退役/归档或待核材料是 inactive，不能继续提交；不删除历史作答。未知判断为 needs_supplement，不映射成 partial。

`PracticeCard={id:string,paper_id:string,paper_title:string,question_id:string,bank_id:string,status:PracticeStatus,created_at:string,goal_ids:string[],topics:TopicRef[],access:Access,latest_attempt_id:string|null}`。
Access 沿用现有 access 对象（id、math_type、year、number、reserved、can_view、confirmed、cross_checked、masked、analysis_allowed、reason），不含题干/解析。

| 方法/路径 | 参数 | 响应 |
| --- | --- | --- |
| GET /api/practices | group_by:'topic'/'paper'/'source'/'batch'='topic'，source:'paper'/'profile'?（省略时合并两种来源），batch_id:string?，status:PracticeStatus?，paper_id:string?，topic_id:string?，include_inactive:boolean=false，分页参数（按组，limit 最大100） | Page<PracticeGroup> + `{counts:PracticeCounts}`；groups 不截断既有布置；多考点练习可出现在不同组，总计按练习 ID 去重 |
| GET /api/practices/{practice_id} | 无 | `{practice:PracticeCard,is_current:boolean,review_reason:string|null,question:object|null,goals:object[],selection_reason:string|null,latest_attempt:Attempt|null,actions:string[]}` |
| GET /api/practices/{practice_id}/attempts | 分页参数 | Page<Attempt>；创建时间、ID 倒序；不带标准答案 |

`PracticeGroup={id:string,label:string,counts:PracticeCounts,items:PracticeCard[]}`。无稳定考点映射的练习放在 unlinked 组，不把训练标签当目录 ID。
`Attempt={id:string,probe_id:string,response:string,image_ids:string[],image_roles:object,answer_exposed:boolean,elapsed_seconds:number|null,created_at:string,assessment:object|null}`；assessment 为已保存批改对象（correct:boolean|null、answer_status?:string、feedback、observations、first_error、possible_causes、reference_reasoning、next_step、needs_material 等）。answer_status 原样提供给前端；旧记录若为 partial，显示“部分正确”，不得转成全错或独立全对。当前写入契约允许 correct/wrong/unknown，本批不修改批改写入 schema；字段缺失时按 correct 展示并保留未知状态。
question 仅包含允许返回的 question_text/question_image、analysis_text/analysis_image、expected/solution_note；隐藏时为 null，inactive 时为 null。参考字段同时要求已经提交且 analysis_allowed。图片 URL 带固定快照 probe_id；不得以当前通用库替代旧练习固定材料。
actions 取 submit/supplement/reveal_question/reveal_analysis 的实际允许子集；草稿仍用 GET/POST /api/drafts，提交/补充/上传/确认查看沿用旧接口。

## 自由练习（题库单题作答）

从题库/考点页单独做一道可查看的题，与原卷、对口练习分开记录（个人表 free_practice_attempts，个人备份包含）。产品规则见本机方案 plans/FREE-PRACTICE.md。

| 方法/路径 | 参数 | 响应 |
| --- | --- | --- |
| GET /api/bank/{bank_id}/practice | 无 | `{bank_id,question_type,collection_id,source:{math_type,year,number,question_type,max_score,book?},question:{question_text?,question_image?},reference:{answer_text?,analysis_text?,answer_image?,analysis_image?}|null,actions:('submit'|'reveal_analysis')[],latest_attempt:FreeAttempt|null,attempt_count:integer}`；reference 仅在已判定或明确 reveal 后返回；question_text 已含选项文字，无单独 options；只有题图的导航占位文字与“参考解析见原图”分别返回 question_text/analysis_text=null，有图就只显示图。无作答历史的 GET 只读当前材料投影，不冻结、不写文件，首次 POST 作答才冻结快照 |
| POST /api/bank/{bank_id}/practice/attempts | `{request_id:UUID,response?:string,choice?:string,image_ids?:string[],image_roles?:object,answer_exposed?:boolean,elapsed_seconds?:number}` | FreeAttempt；同 request_id 同 body 复用，不同 body 409 |
| GET /api/bank/{bank_id}/practice/attempts | offset、limit=20 | `{items:FreeAttempt[],total,offset,limit}`，倒序 |
| GET /api/bank/{bank_id}/practice/attempts/{attempt_id}/materials/{role} | role=question/answer/analysis | 该次固定快照图片；参考需该次已判定或当前已 reveal |

reference 另含 `errata?:[{role,reason,evidence}]`（随该次快照捕获）。

`FreeAttempt={id,bank_id,source:'free_practice',question_type,collection_id,request_id,response,choice,image_ids,image_roles,answer_exposed,elapsed_seconds,created_at,assessment:object|null,job:{id,status}|null,materials:{question:{...},reference:{...}|null}}`；assessment 结构同练习 Attempt。

- 判定：选择题参考可归一为单个 A–D 时同步判定；参考缺失/非单字母走 AI。填空做保守归一（NFKC、空白、`$`、tfrac/dfrac、left/right 等），一致判对，否则交 AI 判等价，不先判错。解答题交 AI。AI 判定返回 assessment=null 与 job，经任务栏/SSE 刷新后重读历史。
- 曝光：看答案/解析沿用 POST /api/bank/{id}/reveal（role=analysis 同时允许答案与解析）。提交先保存曝光快照，再公开参考；看过参考或 answer_exposed=true 记“受提示完成”。
- 每次作答独立记录并冻结题面快照；换通用库后历史仍显示自己的快照。
- actions 在当前可查看且非预留时为 [submit,reveal_analysis]，否则为空（历史仍可读）。预留或遮挡题新作答返回 403，题干遮挡需先 reveal(question)；不要只凭题卡 can_view 放行。
- 图片用 POST /api/answer-images，草稿用 /api/drafts（客户端独立 key）。
- 错误：400 参数/UUID/材料/角色；403 预留或未允许查看；404 题或作答不存在；409 request_id 冲突或活动执行写保护。
- 画像：`preferences.include_free_practice` 默认 true，false 时只从画像和考点聚合中排除，历史不删。GET /api/profile 增加 `free_practice:{total,correct,wrong,pending,independent_correct,assisted_correct}`；考点详情 performance 增加 `source_counts:{exam,practice,free_practice:{同上}}`，free_practice 是绑定该节点的整题作答次数，不证明原子已掌握；successes/failures/state 只用批改明确指出的 topic_ids。

## 画像与按画像选题（B26，已实现）

只读规则：状态沿用考点 performance 聚合，映射 初步掌握→mastered、巩固中→learning、需要关注→weak、证据不足/未覆盖→no_record，原值和 state_reason 保留。无记录不算薄弱；独立做对只计明确独立的正确，受提示和独立性未知分开；没有足够证据时返回 null 加 unavailable_reasons，不补0、不算百分比或能力分。include_free_practice=false 时画像和趋势都不计自由练习。三个 GET 支持 ETag，空工作区返回 200 空结构加 limitations。

| 接口 | 返回要点 |
| --- | --- |
| GET /api/profile/overview | `home_stats{attempts_this_week,independent_correct_this_week,grading_count}`、`totals{pending_analysis_paper_count,unfinished_practice_count}`、`distribution`、`subjects[]`（科→章 ProfileNode，不含原子）、`weak_spots[]`（最多5个章或大考点）、`conclusions{strongest_chapter,weakest_chapter,independent_correct_comparison,unavailable_reasons}`、`recent_mistakes[]`（最多3条）、`next_steps[]`（continue_practice / analyze_paper / profile_batch 三项固定，带 available/reason/count/target）、`profile_batch_eligibility`、`limitations[]` |
| GET /api/profile/trends?weeks=12 | 按周 `weekly[{week_start,week_end,complete,sources:{exam,practice,free_practice}}]`，每项 ActivityCounts `{attempts,correct,independent_correct,assisted_correct,independence_unknown_correct,wrong,unjudged,pending_grading}`；`totals`、`undated` |
| GET /api/profile/nodes/{node_id}/atoms?offset&limit | 章或大考点下的原子 ProfileNode（热力格用），默认60、最多100 |
| POST /api/practices/profile-batch | body `{confirmed:true,request_id:uuid,size:5\|8\|10,scope?:{subject?,chapter_topic_id?}}`；新请求202 `{batch_id,source:'profile_practice',requested_size,status,job_id,reused}`，同 request_id 同内容重放200，换内容409 |
| GET /api/practices/profile-batches/{batch_id} | status queued/selecting/ready/no_candidates/failed/cancelled，`practice_ids`、`targets[{topic_id,name,category:weak\|review_due\|uncovered,reason}]`、`limitations`、`counts` |

ProfileNode：`{id,parent_id,name,kind,math_types,state,state_reason,display_state,distribution{mastered,learning,weak,no_record},successes,failures,assisted,pending,last_attempt_at,ready_question_count,study_ready_question_count,selectable_question_count}`。WeakSpot：`{node_id,name,kind,subject_id,weak_atom_count,observed_atom_count,total_atom_count,recent_failures,recent_judged,failure_ratio,window,basis,evidence[≤3]}`，后端按近28天失败数、失败占比、薄弱原子数、最近失败时间排序；basis只摘录已保存的题目和首错环节，取不到为 null。

按画像选题：目标分 weak（最新有效表现失败）、review_due（只有受提示正确或距上次满14天）、uncovered（当前备考类别有可选 ready 题但无记录），名额按 5:3:2 最大余数分配（5→3/1/1，8→4/2/2，10→5/3/2），不足按 weak→review_due→uncovered 补，不强凑。候选复用原卷选题规则，并排除工作区所有已上传试卷的原题（含同题身份）。任务 kind 仍为 prepare_practice，paper_id=null；完成后前端跳 `/practice?source=profile&view=topic&item=<首个practice_id>&batch=<batch_id>`；练习页带 batch 时只请求并显示这一组（source=profile&batch_id=…），并提供“看全部练习”。

练习卡新增 `origin:'paper'|'profile'|'free_practice'`、`latest_correctness:'correct'|'wrong'|'partial'|'unknown'|null`（与 latest_attempt 的有效批改一致，无有效批改为 null）、`batch_id`、`batch_title`；画像练习的 paper_id/paper_title/question_id 为 null。GET /api/practices 新增 `source=paper|profile`、`batch_id`，group_by 新增 source/batch。access 增加 `collection_label` 与 `book{part,chapter,number}`；参考材料中的“见原图”类占位投影为 null；自由练习403返回 `{error,reason:'masked'|'reserved',message}`（message 可直接展示）。

实现补充：
- overview 的 `totals` 另含 `unread_feedback_count`、`needs_review_count`；另有 `feedback{unread_count,recent_items[≤3]}` 与 `review{total,counts{exam_questions,practice_attempts,free_practice_attempts},paper_issue_count,items[≤5]}`。三个 GET 在个人库、题库写入或日期变化时失效。
- `weak_spots[].evidence[]` 与 `recent_mistakes[]` 带 `question_number:string|null`：原卷来源为保存的题号字符串，对应 `/papers/:paper_id/questions/:question_number`（两段分别 encodeURIComponent）；练习/自由练习为 null，走 practice_id/attempt_id/bank_id。`first_error_stage` 取 entry/modeling/formula/calculation/finalization/unknown（展示：切入/建模/公式/计算/最终处理/环节未知），null 表示没有首错记录，不当作 unknown。
- 目录原子未注明 math_types 时视为对所有备考类别适用。
- `POST /api/feedback/read` body `{request_id:uuid,source:'paper_practice'|'profile_practice'|'free_practice',attempt_id,feedback_revision}`：同请求幂等200，换内容或版本过期409，记录不存在404；只记已读，不改批改。
- 画像练习沿用 GET /api/practices/{id}、/attempts、POST /api/probes/{id}/submit、/api/attempts/{id}/supplement；固定图片为 `GET /api/practices/{id}/materials/question|analysis|answer`（允许时返回，no-store）。GET /api/tasks 的画像任务项带 `source:'profile_practice'`、`batch_id`。
- 题库补图（B27）：BankCard 与题面投影可带只读 `supplemental_figures`（重绘图的角色、说明“按题意重绘”与依据，不含本机路径）；题图 URL 返回的已是原图加重绘图的显示图，前端无需拼接。

## 作答日期、重复上传与画像修正（B28，已实现）

日期：PaperCard、GET /api/papers/{id}.paper、上传响应的 paper 增加 `exam_date:string|null`（YYYY-MM-DD 或 YYYY-MM）、`exam_date_precision:'day'|'month'|'unknown'`、`exam_date_unknown_reason:'not_provided'|'forgotten'|null`、`import_decision:'accepted'|'pending_duplicate'|'withdrawn'`。未填 → null/unknown/not_provided，“记不清” → null/unknown/forgotten，“约某月” → "YYYY-MM"/month；不再默认今天，拒绝未来日/月。旧数据里的完整日期按 day 保留，无法区分是否当年被自动填成上传日，靠用户批量修正。

| 方法/路径 | 参数 | 响应 |
| --- | --- | --- |
| POST /api/papers/import | 原 multipart 加可选 `exam_date`、`exam_date_precision`、`exam_date_unknown_reason`；批量上传逐份传同一值，前端不得在未选择时传今天 | 原字段加 `duplicate_check{status:'clear'\|'same_pdf'\|'same_exam_identity'\|'unresolved',identity{exam_year,math_type}\|null,reason,matches[{paper_id,title,exam_date,exam_date_precision,archived,has_report}]}`、`import_decision`、`decision_revision`。相同PDF 200 复用且不改旧日期；不同PDF同年同卷别 201 保存为 pending_duplicate |
| POST /api/papers/dates | `{confirmed:true,request_id:uuid,paper_ids[1–50],exam_date,exam_date_precision,exam_date_unknown_reason}` | 200 `{updated:[{paper_id,exam_date,exam_date_precision,exam_date_unknown_reason}],reused}`；整批原子写，相关卷有排队/运行中的任务时 409 |
| POST /api/papers/{id}/import-decision | `{confirmed:true,request_id:uuid,decision:'retake'\|'withdraw',decision_revision}` | 200 `{paper_id,import_decision,reused}`；revision 过期、有学习历史时撤回均 409，刷新详情后重试 |

- pending_duplicate 卷不给 analyze 动作，可只读核对切题；GET /api/papers/{id} 在顶层返回当前 duplicate_check 与 decision_revision，刷新后可继续决定。dates 与 import-decision 的 409 响应体带 `reason:'revision_stale'|'has_history'|'task_active'|'request_conflict'|'withdrawn'`。相同PDF复用响应带 `date_ignored:boolean`（本次填的日期与原卷不同而未采用时为 true）。duplicate_check.status='unresolved' 只提示“没能认出是哪一年哪一卷”，不阻止分析。withdraw 是逻辑撤回，只限无分析/批改/练习历史的新上传，默认列表与画像排除。
- 试卷列表已知日期新到旧，未知日期排在后面并显示“日期未知/记不清”；YYYY-MM 不能交给只认完整日期的格式化器。
- 考点详情的已做题列表 date 不再回退上传日期，可为 null，并带 exam_date_precision/exam_date_unknown_reason。
- 考点节点加 `last_attempt_date:{value,precision,unknown_reason}|null`；同一天、同为未知或月份区间重叠时有对有错 → learning（巩固中），state_reason 说明“同一时间范围内有对有错”。
- trends 加 `unplaced_by_precision{month,unknown}`（不能放进某周的作答）；overview 加 `history_counts{month_dated_attempts,unknown_dated_attempts}`。周数与四周对比只计精确到日的作答。
- overview 加 `weak_spots_context{recent_window,recent_judged_count,recent_evidence_sufficient,uses_history_fallback,explanation}`；weak_spot 加 `evidence_period:'recent'|'historical'`、`period_explanation`、`recent_lost_points|null`、`historical_lost_points|null`、各期已知/未知分数题数、`recent_exam_failure_count`、`recent_practice_failure_count`、`historical_failures`、`historical_exam_failure_count`、`historical_practice_failure_count`、`loss_attribution:'related_question_loss'`、`loss_basis:'saved_estimate'|'mixed'|null`。排序：近期在前、历史补位在后；组内按原卷已知失分 → 原卷错题数 → 练习错题数 → 错误比例 → 薄弱原子数。失分为“涉及的原卷失分（按已保存估分）”，null 显示“分数未知”不填 0，各章失分不能相加。
- evidence 与 recent_mistakes 加 `exam_date`、`exam_date_precision`、`exam_date_unknown_reason`、`score_earned`、`max_score`、`lost_points`、`loss_basis`、`loss_unavailable_reason:'missing_score'|'invalid_score'|'score_conflict'|'not_exam'|null`。
- overview 加 `first_error_summary|null`：`{period:'recent',window,wrong_count,attributed_count,unattributed_count,stages[{stage,count}],dominant_stage,dominant_count,statement,evidence[≤3]}`（evidence 带与 weak_spots evidence 同写法的 label）；近期≥5道错题、≥3道有首错记录、唯一最多的环节≥3道且占错题≥50% 才返回，否则 null，前端不显示该卡、不自行拼结论。

## 考点与题库

| 方法/路径 | 参数 | 响应 |
| --- | --- | --- |
| GET /api/knowledge/topics/{topic_id} | 无；支持已发布目录的历史 ID 重定向 | `{topic:{id:string,parent_id:string|null,name:string,kind:string,definition:string,conditions:string[],boundaries:string[]},performance:{state:string,state_reason:string,successes:integer,failures:integer,pending:integer,attempt_count:integer},question_counts:{completed:integer,bank:integer},collection_counts:[{collection_id:string,bank:integer,ready:integer,completed:integer}],practice_counts:PracticeCounts}`；collection_counts按子树同题实体去重、稀疏（无关联题集可缺），各题集计数不能相加当全局数 |
| GET /api/bank/collections | 无 | `[{id:string,name:string,kind:'exam'|'book'|'other'|'example',total:integer,ready:integer,math_types:[{math_type:1|2|3,total:integer,ready:integer}]}]`，按排序返回；total为来源题记录数，ready为当前有效就绪数；math_types按适用数学类别稀疏分组（只列有题的类别，多类别题在各类别都计） |
| GET /api/bank | math_type:''/'1'/'2'/'3'=''，year:string=''，topic_id:string?，collection:string?（未知题集400；指定即分页响应），q:string?（题面文字，只搜题干含选项、不搜解析；与其他筛选组合并触发分页；不返回预留或当前遮挡题），分页参数 | Page<BankCard>，math_type按题目适用数学类别过滤（对所有题集生效）；真题按年份降序、math_type、题号、bank ID 稳定排序，教辅题集按book的篇、章、原题号/定位（数值）排序；考点筛选包含其子树，通过已核关联投影，不按导航标签猜关联 |

BankCard 是原 public_bank(view=library)（id、math_type、year、number、can_view、reserved、reason、analysis_allowed、stem、tags、question_image、analysis_image）加 `{collection_id:string,math_types:number[],question_type:string|null,max_score:number|null,question_text?:string,analysis_text?:string,book?:{title,edition,part,chapter,number,locator}}`（book各字段string|null，仅教辅题；math_type仍只表示考试身份，适用类别看math_types；无题图资源时不返回question_image/analysis_image）；analysis_text 仅在 analysis_allowed 时返回，真正展开解析仍走 POST /api/bank/{id}/reveal 记录曝光。BankCard 另有 `errata:[{role,reason,evidence}]`（无勘误为空），在参考解析处显示“本题已按勘误修正”；role 为 answer/analysis 的依据可能含答案，展开前同样走 reveal 记曝光，不当作普通题干说明展示。题库浏览保持 library 策略；练习遮挡按 practice access，不混用入口。
考点树用 GET /api/knowledge/catalog/tree 一次取全：`{release_id:string|null,total:integer,items:[{id,parent_id,name,kind,aliases:string[],child_count:integer}]}`（child_count为直接子节点数，不含定义与个人表现）；关联题复用现有 GET /api/knowledge/catalog、/api/knowledge/links、/api/knowledge/links/summary；/api/knowledge/links与/api/bank/search新增可选collection过滤（筛选先于同题去重），题卡与existing_exercises带collection_id（已完成原题对不上库题时为null），/api/bank/{id}/topics与批量/api/bank/topics题卡同样带collection_id。本批不新增画像图表。应用托管 dist 时，dist 中真实存在的文件按静态返回，其余非 /api 路径回退 index.html（考点 ID 含点也可直接打开/刷新）；/api 下未知路径保持 404。

## 任务摘要与动作

GET `/api/tasks?status=TaskStatus&offset=0&limit=20` 返回：

```text
Page<Task> & {
  status: 'idle'|'connecting'|'running'|'attention_required'|'agent_unavailable',
  availability: {status:'available'|'checking'|'unavailable',
                 reason:null|'not_installed'|'not_logged_in'|'disabled'|'other',
                 message:string},
  active:Task|null, queued_count:integer, failed_count:integer
}
Task = {
  id:string, kind:string, paper_id:string|null, paper_title:string|null,
  attempt_id:string|null,
  status:'queued'|'running'|'completed'|'blocked'|'failed'|'cancelled',
  progress:{message:string}, error:string|null,
  created_at:string, updated_at:string,
  allowed_actions:('retry'|'cancel')[]
}
```

同卷同 kind（批改另按 attempt_id）之后已有 completed 任务时，更早的 failed/interrupted/blocked 不再计入待处理（历史仍在，非取消或删除）。分页只影响 items，active/counts 始终是全队列摘要，不受 status 筛选影响。排队/运行优先，其次需处理项，最后历史；同级创建时间倒序并以 ID 排序。status 参数枚举不合法返回 400。
kind 沿用 workflow kind。进度只到试卷（如“正在分析《2023 数学一》”），不猜题号/模型完成比例；不输出会话 ID、聊天、工具日志、输入或执行令牌。error 是已保存业务错误；安装登录问题在 availability 中表达。

POST `/api/tasks/{job_id}/action` body `{action:'retry'|'cancel'}` 返回该任务操作后的 `GET /api/tasks` 默认第一页摘要。仅 allowed_actions 中的动作可执行，否则 409；不存在 404。运行中的任务不提供动作；failed/blocked且尚未建立执行任务的可cancel；已建立执行任务的failed/interrupted阶段，在该任务已终止、无保存结果且本工作区无其他执行中任务时也可cancel（标为已取消，原卷、作答、任务历史和已存结果保留）。failed 任务在无其他执行时可 retry：保留旧执行记录，新建请求、任务和会话重新执行；已有保存回执的任务不会重跑。恢复备份的 recovery_required 保持显式 retry，不能自动重放旧执行。

每个任务新开一次 Codex 会话，结束即关闭；应用重启或断线时，已保存回执的任务直接完成，无回执的任务标为 failed（error 为“执行已中断；重试将在新会话重新执行”）。后台在有排队任务时自动检查命令和账户，首次有工作时立即检查，失败后约30秒重新检查，无需用户点击连接。未检查时 availability 为 checking；未安装/未登录不消费排队任务，保存数据始终可读。所选模型/强度不可用时任务在执行前标为 failed，error 给出可读提示。

GET `/api/agent/models`：只读，不创建任务或会话。200 `{status:'available'|'checking'|'unavailable',reason:null|'not_installed'|'not_logged_in'|'other'|'disabled',message:string,items:[{id:string,name:string,efforts:string[]}]}`。items 来自本机 app-server 的 model/list，不是静态枚举；disabled 表示后端未启用 Agent；checking 可稍后重读。

## SSE

GET `/api/events`：`Content-Type:text/event-stream`，no-store，禁代理缓冲。沿用本地同源边界，带 Origin 的 SSE 请求也必须同源。不带分页。一个页面只开一条连接。

每个有数据的事件有 `id: <epoch>:<seq>`；data 是 JSON：

| event | data |
| --- | --- |
| snapshot | `{epoch:string,seq:integer,tasks:TasksResponse,preparation:{items:Progress[]},resource_tokens:{personal:string,library:string}}` |
| tasks.changed | `{epoch,seq,tasks:TasksResponse}`；轻量默认第一页摘要 |
| preparation.changed | `{epoch,seq,preparation:{items:Progress[]}}`；Progress 沿用本地 progress.json 的 paper_id/status/phase/message/updated_at 及可选 pages_done/pages_total 等字段 |
| resources.changed | `{epoch,seq,resources:('papers'|'questions'|'practices'|'knowledge'|'bank'|'preferences')[],resource_tokens:{personal:string,library:string}}` |

每次连接（包括携带 Last-Event-ID）总是先发权威 snapshot，不补播旧事件，不要求持久事件日志。服务重启 epoch 改变，客户端刷新已加载 query；同 epoch 重连也按 snapshot 校准。seq 在服务实例内单调递增，连接间可有间隔。heartbeat 约15秒，为 SSE 注释，不增加 seq。断开由 EventSource 自动重连（retry 约3秒）；断线期间保留已显示数据，恢复后校准。

后端每实例一个轻量观察器检测双库已提交版本、任务投影及 PDF 进度文件；不按客户端重算 bootstrap/loop，不推数学内容。无变化不发数据事件。客户端消费慢时合并变化；下一次权威状态覆盖中间状态，不阻塞写事务。观察失败发送 `event: error`、`data:{error:string}` 后关闭连接，由客户端重连；内部详细异常不输出到界面。

## 兼容与后续

旧 bootstrap、loop、profile、agent/state、preparation 与所有写入口继续可用；新增读取不改变学习记录、不自动 reveal、不触发新学习任务。资源接口只读取已保存结果，后台自动连接独立于读取。
本批不更新学习结果 schema/Skill，不回填旧报告，不做计时图表。客户端不应把缺失摘要、未知题型、未关联考点或未核定分数显示为 0/错误/已掌握。

## 数据状态与备份

GET `/api/data/status`：只读，不启动任务，不自动迁移。响应 `{data_dir:string,library_dir:string,library_exists:boolean,library_env_override:boolean,databases:{learning|library|session:{bytes:integer,exists:boolean}},invalid_file_references:{count:integer,examples:FileReference[]},last_backup_at:string|null,path_migration:{pending:boolean,ready_count:integer,unresolved_count:integer,historical_reference_count:integer,plan_sha256:string}}`。FileReference 包含 store/table/id/field/old/relative/exists/verified 等定位元数据，不含题目正文。该接口读取当前文件状态，不使用 ETag/304；缺库以 exists=false 表示，不创建数据库。待迁移及缺文件不是普通网络错误。library_dir 是解析后的实际通用库位置；library_exists 表示该目录存在（数据库是否存在另看 databases.library.exists）；library_env_override 表示 MATHLENS_LIBRARY_DIR 覆盖规则正在此工作区生效，即使环境变量与文件配置的值相同也为 true。环境变量指向其他工作区时为 false。

立即备份复用 POST `/api/maintenance/backup`，响应 `{path:string,files:integer}`；列表 GET `/api/maintenance/backups` 返回 `{backups:[{name,bytes}]}`，无需新增写接口。POST `/api/maintenance/restore` `{name,library_dir?,confirm_older_library?:boolean}` 返回中含 `library_status:'same'|'newer'|'older'` 与 `library_notice`；当前题库比备份旧时默认返回 library_older，需布尔 confirm_older_library=true 才恢复；异库 library_mismatch、缺库 library_missing。

POST `/api/preferences` 仅合并实际传入字段，省略 reserved、mask_same_type、paper_marking_convention、study_type、execution_profiles 均保留旧值；显式非法值返回400。

Preferences 含 `execution_profiles:{judgment:{model:string,effort:string},organization:{model:string,effort:string}}`，默认 judgment=gpt-6-luna/xhigh、organization=gpt-6-luna/high。judgment 用于 analyze_paper、review_question、grade_attempt、review_practice、maintain_catalog、annotate_questions；organization 用于 prepare_practice、organize_knowledge、summarize_paper。POST 可只传一档（按档合并，不重置另一档），每档须同时含 model 与 effort；`execution_profiles:null` 恢复默认。保存不启动任务，下一个任务起生效。

文件路径升级为显式 CLI：`python scripts/migrate_file_paths.py --dry-run --report <私有报告路径>`，核对 changes/unresolved/historical_references 后用 `--confirm <plan_sha256>`。确认前自动执行现有完整备份；找不到或散列不匹配的引用不猜配、不删除。只对 workspace.json.library 这一个根目录位置配置开例外：同盘存相对工作区的位置（标准布局为 ../../library），跨盘允许绝对路径，迁移预演不会把已正确配置的跨盘绝对路径反复列为待迁移。预演 changes.relative 在该配置项跨盘时可为绝对目标；业务文件引用仍只允许所属根目录内的相对路径，拒绝绝对和越界路径。受散列保护的不可变历史证据单独报告，不能直接改写后继续宣称旧回执有效。

## F5 写入契约

全部 body 默认 JSON；上传使用 multipart/form-data。错误统一 `{error:string}`。结构/参数错误400，同源校验403，当前会话占用或状态冲突409；不向学生展示原始协议字段。下面标注404的入口明确区分资源不存在，其他旧写入口可能以400返回“不存在”。request_id 在出现时必须为 UUID（推荐 crypto.randomUUID()），同一次重试复用同一UUID，不同操作生成新UUID；缺少 request_id 的旧入口由服务器生成标识，不能宣称它们支持客户端幂等。

| 方法/路径 | body | 成功响应 | 额外失败边界 |
|---|---|---|---|
| POST /api/preferences | 部分 `{study_type?,mask_same_type?,reserved?,paper_marking_convention?,execution_profiles?}`，类型同GET | 200 Preferences，未传字段保留 | 400 非法类别/预留范围/开关 |
| POST /api/maintenance/backup | `{}` | 200 `{path:string,files:integer}` | 409 当前写入受占用 |
| POST /api/papers/import | multipart `file:PDF,title?:string,exam_date?:string`，上限80MB | 201 `{paper,sha256,created_questions?,warnings?,agent_queued:false,analysis_warning?}`，只保存PDF并本地切题，不排AI任务；重复PDF为200 `{paper,sha256,reused:true}` | 400 非可读PDF/超限；文件已保存但后续准备失败时保留paper并给analysis_warning |
| POST /api/papers/{id}/analyze | `{confirmed:true}` | 201 `{paper,questions,engine,message,warnings,created_questions,agent_task,agent_queued:true,job_id}`；唯一的开始分析入口，首次也须确认 | 400 未确认、归档/原卷不可读 |
| POST /api/papers/{id}/archive | `{confirmed:true}` | 200 `{paper_id,archived:true,reused?:boolean,updated_at?:string}` | 400 未确认 |
| POST /api/papers/{id}/restore | `{confirmed:true}` | 200 同archive，archived=false | 400 未确认 |
| POST /api/papers/{id}/score | `{score:number,total_score:number,math_type:1\|2\|3,confirmed:true}` | 200 `{paper_id,score,total_score,score_confirmed_at}` | 400 分值非法、未确认、归档 |
| POST /api/papers/{id}/confirm | `{numbers:(string\|number)[],scores?:(number\|string)[],subject?:string}` | 201 `{paper_id,created_questions,status:'analyzed'}` | 409 已有题目；纠正请用下方专用入口 |
| POST /api/papers/{id}/resummarize | `{confirmed:true}` | 201 `{paper_id,agent_submitted:true}` | 400 未确认/未完成分析/助手未初始化 |
| POST /api/papers/{id}/prepare-practice | `{request_id:UUID}` | 201 TasksResponse，结构同GET /api/tasks，无session_id、对话或票据 | 404 无卷；409 归档/会话占用；400 原卷尚未核对通过或原PDF变化 |
| POST /api/agent/task（旧） | `{kind:'prepare_practice',paper_id,request_id:UUID}` | 200 旧会话快照，仅保留兼容；新前端改用上方入口 | 400 非UUID、任务前置不满足；409 会话冲突 |
| POST /api/questions/{id}/review | `{request_id:UUID,report_id:string,note?:string,image_ids?:string[],image_roles?:object}` | 201 `{agent_queued:true,job_id}` | 400 过期报告/附件角色不符/无原题；409 会话占用 |
| POST /api/bank/{id}/reveal | `{role:'question'\|'analysis',confirmed:true}` | 200 Access状态，沿用GET里的access结构 | 400 未确认、预留、题干尚未允许查看 |
| POST /api/answer-images | multipart `files` 1–4张，每张<=8MB，PNG/JPEG/WebP | 201 `{images:[{id,url,width,height}]}` | 400 类型/像素/大小/数量非法 |
| POST /api/probes/{id}/submit | AttemptBody | 201 `{attempt_id,status?,assessment:null,job:{id,status},reused?:boolean}` | 400 作答为空/已失效/预留/请求标识被用于不同内容；409 会话占用 |
| POST /api/attempts/{id}/supplement | AttemptBody（response为本次追加文本） | 200 `{attempt_id,status:'awaiting_assessment',job:{id,status},reused?:boolean}` | 400 作答/附件非法、关联失效、请求标识冲突；409 会话占用 |
| POST /api/probes/{id}/feedback | `{attempt_id:string}` | 200 `{attempt_id,job:{id,status}}` | 400 作答不属于该练习或已归档 |
| POST /api/tasks/{id}/action | `{action:'retry'\|'cancel'}` | 200 TasksResponse | 404 无任务；409 不在allowed_actions或远端状态未核清 |

AttemptBody=`{response?:string,image_ids?:string[],image_roles?:{[image_id]:'own_work'|'external_solution'|'marking'},answer_exposed?:boolean,elapsed_seconds?:number,request_id?:UUID}`。内部角色值只用于结构字段；面向学生分别显示“你的作答 / 参考解析 / 事后批改”。保存提交并不自动判对；批改状态通过tasks/SSE与练习读接口刷新。

### 未分析切分纠正方案

POST `/api/papers/{id}/questions/correct`，body=`{confirmed:true,questions:[{number:string,question_ids:string[]}],delete_question_ids?:string[]}`。请求完整分配本卷全部现有题目，每个ID恰好出现一次：一个ID一组即重新编号，多ID一组即合并，误切题须显式列入删除列表。每组保留首个ID、按页/坐标合并去重regions，并保存纠正前快照；不合成新的学生作答，不产生学习任务。返回200 `{paper_id,question_ids:string[],deleted_question_ids:string[],status:'corrected'}`。无卷404，未确认/重复编号/遗漏或跨卷ID400；归档、已有诊断/练习历史、有排队或运行任务409。本版只处理整卷尚未进入诊断/练习历史的切分，已诊断题一律保留。再次analyze保留纠正结果；原PDF变化则400，不能沿用旧纠正。前端需先结束/取消上传自动排入的分析任务再纠正。

拆分（B20）：questions[] 的组可带 `split:{page:integer,y:number,lower_number:string}`，该组只能有一个旧ID；number 为上半题号，lower_number 为下半题号，均不得与其他组重复。page 从 1 起，y 为该页 PDF 点坐标（自顶向下，用 evidence_regions 换算），须严格穿过该题某个 region 且上下都留有非空区域；跨页时较早页归上半。上半保留旧ID，下半分配新ID，响应 question_ids 按组依次列上、下。可与其他组的重编号/合并/删除同次提交，但同次不能把拆出的半题再并入别组（先拆分提交再合并）。题干按本地 OCR 定位行归属上下，无定位行时下半为“待补充题干”。400 另含 split 组非单 ID、page/y 非法或不穿过题区、拆不出上下两部分。

调整切图（B23）：POST `/api/papers/{paper_id}/questions/{question_id}/regions`，body=`{confirmed:true,request_id:uuid,regions:[{page:integer,top:number,bottom:number}]}`，1–4段，page从1起，top/bottom为该页PDF点坐标且`0≤top<bottom≤页高`，每段按整页宽保存为`role:'question_and_work'`。只改当前显示用的题图区域，诊断、作答、练习历史和证据不变，已分析试卷也可用；旧区域写入record_versions（`question_regions`）。同一request_id重放返回原结果并带`reused:true`，换内容复用则409。返回200 `{paper_id,question_id,status:'updated',regions:Region[],request_id,reused}`。试卷或题目不存在404；未确认、段数/页码/坐标非法、原PDF缺失400；已归档或有排队/运行任务409。evidence_urls带区域散列参数`&v=`，/evidence响应`Cache-Control: no-store`，调整后刷新即见新图。

### 导入题集包（B21）

格式见[题源接口](bank-source-interface.md#题集包)。设置页先预演再确认：

- POST `/api/library/collection-packs/preview`，multipart 字段 file（zip）。只暂存到系统 TEMP，不写库。返回 `{package_sha256,plan_sha256,package_version,created_at,sources,trust_notice,collection,counts:{total,ready,needs_review,needs_catalog,unannotated},added:bank_id[],updated:bank_id[],unchanged:bank_id[],catalog:{status:'current'|'upgrade'|'keep_current'|'conflict',current_release_id,required_release_id},collection_conflicts:[],annotation_summary,applied:false}`。ready 题数看 counts.ready；annotation_summary.entries 是索引条目数，不等于题数。
- POST `/api/library/collection-packs/confirm` `{package_sha256,plan_sha256,confirmed:true}`：重新核对包和库，自动备份通用库后单事务写入，返回同结构加 `applied:true,backup:{path,...}`。不改个人工作区数据；无变化也可安全确认。真题包首次确认约 2.5 分钟，前端按长请求处理；期间读接口照常，其他写入 409。
- 错误 `{error}`：400 格式/路径/散列/schema/勘误不合法，404 暂存包已失效（重新预演），409 预演过期、题集或目录定义冲突、维护中，413 超限（压缩包 1GiB、解压 2GiB/30000 文件）。确认表示接受该包的题集、目录和共享标注来源；散列不证明发布者或数学正确性。

### 数据状态轻量检查

GET `/api/data/status` 保持已有字段，仅查各库大小、定位列及文件存在性，不执行完整preview、不解析历史TEXT JSON、不计算内容散列。path_migration.unresolved_count 是格式上待预演确认的引用及配置数量，ready_count=0；historical_reference_count=0 表示此轻量入口不统计历史引用；示例中的 sha256/expected_sha256/verified 为 null 表示未做内容校验，不应显示为散列通过。plan_sha256 仅为轻量状态摘要，不能用于确认迁移，确认码必须取 CLI --dry-run 的完整预演。完整散列校验/候选映射/历史盘点仍由显式迁移命令执行。

### 开发 Origin

默认仅接受原有本机同源写入和SSE。开发进程可设置 `MATHLENS_DEV_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`，只允许明确的本机HTTP(S) Origin，不接受通配符、路径或外部域名。配置的Origin获得对应CORS响应与预检支持，暴露ETag/Cache-Control，仍检查API目标Host必须为本机；该配置不扩大业务文件路径权限。
