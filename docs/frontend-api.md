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
| GET /api/questions/{question_id} | 无 | `{question:QuestionSummary & {stem:string,regions:Region[]},diagnosis:Diagnosis|null,topics:TopicRef[],evidence_urls:string[],practice_counts:PracticeCounts,previous_id:string|null,next_id:string|null,capabilities:{step_comparison:false}}` |
| GET /api/papers/{paper_id}/summary | 无 | `{status:'missing'|'available',result_id:string|null,created_at:string|null,summary:object|null}`；summary 为已保存 summarize_paper.result（overview、key_findings、improvements、next_actions、limitations、source_refs），不生成新总结 |

`AnalysisState={report_id:string|null,completion:string|null,review_status:string|null,summary:string,limitations:string[]}`。`TopicRef={topic_id:string,name:string}`。
Region 为现有 `{page:integer,bbox:number[4],role:string}`（PDF 点坐标）；evidence_urls 使用现有 `/api/questions/{id}/evidence?region=N`。
Diagnosis 为现有 present_diagnosis 的逐题对象：stem、observation、correctness、answer_evidence（student_work/student_state/marking/marking_note）、correct_parts、first_error、solution_guide、reference_answer/reference_reasoning、hypotheses、cause_summary、knowledge、fingerprint、regions 等已保存字段；旧报告缺字段保持兼容，不伪造步骤。
TopicRef 只来自有效知识映射；weak_topics 是已关联且 state=需要关注 的考点，不根据字符串造 ID。

## 练习

`PracticeCounts={pending:integer,grading:integer,graded:integer,needs_supplement:integer,inactive:integer,total:integer}`。
`PracticeStatus='pending'|'grading'|'graded'|'needs_supplement'|'inactive'`。失效计划、退役/归档或待核材料是 inactive，不能继续提交；不删除历史作答。未知判断为 needs_supplement，不映射成 partial。

`PracticeCard={id:string,paper_id:string,paper_title:string,question_id:string,bank_id:string,status:PracticeStatus,created_at:string,goal_ids:string[],topics:TopicRef[],access:Access,latest_attempt_id:string|null}`。
Access 沿用现有 access 对象（id、math_type、year、number、reserved、can_view、confirmed、cross_checked、masked、analysis_allowed、reason），不含题干/解析。

| 方法/路径 | 参数 | 响应 |
| --- | --- | --- |
| GET /api/practices | group_by:'topic'/'paper'='topic'，status:PracticeStatus?，paper_id:string?，topic_id:string?，include_inactive:boolean=false，分页参数（按组） | Page<PracticeGroup> + `{counts:PracticeCounts}`；groups 不截断既有布置；多考点练习可出现在不同组，总计按练习 ID 去重 |
| GET /api/practices/{practice_id} | 无 | `{practice:PracticeCard,is_current:boolean,review_reason:string|null,question:object|null,goals:object[],selection_reason:string|null,latest_attempt:Attempt|null,actions:string[]}` |
| GET /api/practices/{practice_id}/attempts | 分页参数 | Page<Attempt>；创建时间、ID 倒序；不带标准答案 |

`PracticeGroup={id:string,label:string,counts:PracticeCounts,items:PracticeCard[]}`。无稳定考点映射的练习放在 unlinked 组，不把训练标签当目录 ID。
`Attempt={id:string,probe_id:string,response:string,image_ids:string[],image_roles:object,answer_exposed:boolean,elapsed_seconds:number|null,created_at:string,assessment:object|null}`；assessment 为已保存批改对象（correct:boolean|null、answer_status?:string、feedback、observations、first_error、possible_causes、reference_reasoning、next_step、needs_material 等）。answer_status 原样提供给前端；旧记录若为 partial，显示“部分正确”，不得转成全错或独立全对。当前写入契约允许 correct/wrong/unknown，本批不修改批改写入 schema；字段缺失时按 correct 展示并保留未知状态。
question 仅包含允许返回的 question_text/question_image、analysis_text/analysis_image、expected/solution_note；隐藏时为 null，inactive 时为 null。参考字段同时要求已经提交且 analysis_allowed。图片 URL 带固定快照 probe_id；不得以当前通用库替代旧练习固定材料。
actions 取 submit/supplement/reveal_question/reveal_analysis 的实际允许子集；草稿仍用 GET/POST /api/drafts，提交/补充/上传/确认查看沿用旧接口。

## 考点与题库

| 方法/路径 | 参数 | 响应 |
| --- | --- | --- |
| GET /api/knowledge/topics/{topic_id} | 无；支持已发布目录的历史 ID 重定向 | `{topic:{id:string,parent_id:string|null,name:string,kind:string,definition:string,conditions:string[],boundaries:string[]},performance:{state:string,state_reason:string,successes:integer,failures:integer,pending:integer,attempt_count:integer},question_counts:{completed:integer,bank:integer},practice_counts:PracticeCounts}` |
| GET /api/bank | math_type:''/'1'/'2'/'3'=''，year:string=''，topic_id:string?，分页参数 | Page<BankCard>，按 bank ID；考点筛选包含其子树，通过已核关联投影，不按导航标签猜关联 |

BankCard 是原 public_bank(view=library)（id、math_type、year、number、can_view、reserved、reason、analysis_allowed、stem、tags、question_image、analysis_image）加 `{question_type:string|null,max_score:number|null}`。题库浏览保持 library 策略；练习遮挡按 practice access，不混用入口。
考点树及关联题复用现有 GET /api/knowledge/catalog、/api/knowledge/links、/api/knowledge/links/summary（既有参数和响应不变）。本批不新增画像图表。

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

分页只影响 items，active/counts 始终是全队列摘要，不受 status 筛选影响。排队/运行优先，其次需处理项，最后历史；同级创建时间倒序并以 ID 排序。status 参数枚举不合法返回 400。
kind 沿用 workflow kind。进度只到试卷（如“正在分析《2023 数学一》”），不猜题号/模型完成比例；不输出会话 ID、聊天、工具日志、输入或执行令牌。error 是已保存业务错误；安装登录问题在 availability 中表达。

POST `/api/tasks/{job_id}/action` body `{action:'retry'|'cancel'}` 返回该任务操作后的 `GET /api/tasks` 默认第一页摘要。仅 allowed_actions 中的动作可执行，否则 409；不存在 404。复用原 workflow_action/原任务回执和重试，不另建身份绕过未知远端执行。运行中的轮次、连接核对或外部占用期间不提供任务动作；已失败且仍绑定原轮次时可提供 retry，先核对原远端状态再决定是否重试。恢复备份的 recovery_required 保持显式 retry，不能自动重放旧执行。历史直接任务无 workflow 记录时仅在仍绑定原活动轮次的失败状态下允许重试。

默认应用后台在有排队/未确认原任务时自动连接；空工作区不创建远端学习会话。先检查命令和账户，再恢复原会话并核对原 turn，之后才派发；不因连接失败换会话或重复保存。首次有工作时立即检查，失败后约30秒重新检查，无需用户点击连接。空闲、尚未检查登录时 availability 为 checking；不启动空会话探测登录。未安装/未登录不消费排队任务，保存数据始终可读。显式释放/外部占用不自动抢回。

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

GET `/api/data/status`：只读，不启动任务，不自动迁移。响应 `{data_dir:string,library_dir:string,databases:{learning|library|session:{bytes:integer,exists:boolean}},invalid_file_references:{count:integer,examples:FileReference[]},last_backup_at:string|null,path_migration:{pending:boolean,ready_count:integer,unresolved_count:integer,historical_reference_count:integer,plan_sha256:string}}`。FileReference 包含 store/table/id/field/old/relative/exists/verified 等定位元数据，不含题目正文。该接口读取当前文件状态，不使用 ETag/304；缺库以 exists=false 表示，不创建数据库。待迁移及缺文件不是普通网络错误。

立即备份复用 POST `/api/maintenance/backup`，响应 `{path:string,files:integer}`；列表 GET `/api/maintenance/backups` 返回 `{backups:[{name,bytes}]}`，无需新增写接口。

POST `/api/preferences` 仅合并实际传入字段，省略 reserved、mask_same_type、paper_marking_convention、study_type 均保留旧值；显式非法值返回400。

文件路径升级为显式 CLI：`python scripts/migrate_file_paths.py --dry-run --report <私有报告路径>`，核对 changes/unresolved/historical_references 后用 `--confirm <plan_sha256>`。确认前自动执行现有完整备份；找不到或散列不匹配的引用不猜配、不删除。workspace.json.library 是根目录位置配置，允许相对 ../ 指向共享库；业务文件引用只允许所属根目录内的相对路径。受散列保护的不可变历史证据单独报告，不能直接改写后继续宣称旧回执有效。
