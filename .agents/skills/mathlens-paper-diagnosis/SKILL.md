---
name: mathlens-paper-diagnosis
description: 在 MathLens 中分析已完成试卷或一道原卷题，核验解法并定位最早实质性错误；逐题交付思路、切入点和可能原因，完成当前分析阶段，不用于开发代码。
---

# 原卷诊断

收到 `kind=review_question` 时仅执行单题复核：从 `learning_task.question_review` 取得指定原题、父报告与可选材料。先 `read_paper({paper_id,question_id})` 阅读完整原页、自动放大的局部及附加照片，需要时再按PDF点坐标调整regions。原报告可能判读有误，不继承其“不可辨”结论，也不把复核请求当正确答案；黑笔原选项、红笔更正和核验答案分别观察。只交付指定question、该题review与聚合summary/priorities（移除已解决的补拍提醒）；仅从允许的resolved_issue_indexes/resolved_limitation_indexes中移除确已解决项，其他未决项保留。completion表示合并后的整卷分析覆盖与核对，不能因学生空白、原因未知、未核总分而保留partial；仍有影响题意/判定/关键解法的其他问题时才保留partial与needs_review；仍不可辨时指出具体需补拍位置。不重做其他题、不修改练习作答，不把补拍当新增独立成功。程序保留旧版本，整卷核对通过并远端成功后才自动派发独立选题。

本技能执行“分析试卷”任务，不要求学生逐题校对或纠正 Agent。目标流程见 `docs/paper-review-workflow.md`；当前写回仍使用下文已接通的工具契约。

context返回learning_task时，以它的result_schema、task_id、input_revision为本次固定契约，优先于下文旧报告格式。用apply_report操作、payload为`{result:完整任务结果JSON}`交付。整卷任务先read_paper读完原卷页图，单题任务只读相关页和复核材料；取得回执后结束当前分析任务，不自行选题。应用仅在completion=complete、report.review.status=verified、结果已保存且远端轮次成功结束后，向同一session派发独立prepare_practice。存在影响判题的冲突先保存初步分析并暂缓选题，不把核对成本转给学生。

从网页上下文取得 paper_id/question_id。先用内置 `mathlens` 工具 `context({paper_id})`，其中 task_packages 已内联切题任务包；read_skill 同时返回 report_contract，无需用终端读取 JSON 或报告文档。用 read_paper 核对原图，每次最多 4 页，清晰时避免反复读取同页。页面快照不是用户作答。独立 CLI 可用 `scripts/agent_tasks.py context --paper <paper_id>`。

task_packages若含有明确的本卷user_feedback，将其作为用户补充证据保存和采用；用户已明确某题判错时，不因具体原选项不可辨又把已知正误改成未知，仍可保留原答转录/错误环节未知。核对请求review_request只限定需复查的范围，不把开发者提示当作数学答案；其余已保存且无冲突的分析不必反复重新推导。

read_paper返回bank_locator_candidates时，先按其中的出处候选用read_bank核对，避免从全库反复找年份题号；它只是title/source_name及已保存类别生成的导航，不是同题确认、ready证明或知识映射。没有唯一年份、出处冲突或未命中时，不猜配最近年份，不从备考设置推断原卷类别，仍按原图分析；补强选题不因此按数学类别过滤。原卷可在已有题库找到时，先独立理解题意并核验解法，再用read_bank比对实际题干、选项与条件，再读参考解析交叉核验，尤其是结论变化、批改冲突或必要/充分条件判断。不能只凭年份题号认同题，也不能把旧报告当参考答案；不同来源有冲突时明确保留，不为通过核对而猜选一边。

仅在本任务schema支持references时使用固定通用参考：learning_task.paper_references列出捕获的候选、annotation_id和材料角色。先read_paper核原题，再read_bank（可role=all）逐项对照条件、目标和选项/图；task_context的bank_ids可读该版本通用分析，topic_ids读捕获定义。确认等价后验证关键推导并复用，不必另写一套解法；共享索引没有推导时仍独立求解。references逐题记录实际对照依据及该annotation_id，不能凭年份题号确认；不确定、材料不同或无候选时留空，继续独立分析。参考变化/不再就绪时不换绑新版本，不拿参考补造学生作答、首错或原因。原卷对题也按同一流程核步骤；后续独立知识整理复用已有ID线索。旧schema不补references。

区分题干、独立作答、考试中自查修正、事后批改及已给提示。笔迹含义采用本次任务的预设提示词及 preferences.paper_marking_convention，本卷用户明确说明的例外优先。不反复询问已配置的黑字/红字含义。完成整卷识别、解题思路和初步诊断，不以学生回答额外问题作为前置条件。

1.1及后续契约逐题填写answer_evidence：student_work只转录学生原作答，不把印刷内容、红笔更正或参考答案填进去；student_state区分visible/not_attempted/unreadable；marking及marking_note描述可见的判对勾、判错叉或更正内容。红笔补出正确答案不代表学生原本答对，红色对勾也不能一概算作判错。已明确批错但错误环节不清时，correctness保留wrong、first_error可为空，原因未知另记；空白/“不会”不虚构计算首错或成功证据。

整页看不清颜色、改写或最终选项时，使用同一read_paper操作的regions局部放大：`{paper_id,regions:[{page:1,bbox:[20,480,580,590]}]}`，每次最多4区，使用原PDF点坐标。局部图帮助判别笔迹，不替代读完整页；不要反复返回相同缩略整页，或用正确参考答案填补看不清的原作答。

交付前核对每题的原作答、批改含义、判定和skill_events是否一致，特别复看“参考答案恰好与红笔更正相同”的题。review.status=verified只表示这些依据已核对，无未解决的判题冲突，不表示每个错因都已查明。有关键矛盾则needs_review并列具体issues，不因要进入选题而填写通过。参考推导按题干原条件核验，不能因最终数值正确而省略条件/延拓/定义域检查。

已由卷面或用户明确证据确认答错，即使原选项转录不清、首错步骤和原因未知，也可以完成这道题的正误核对；将这些限制放在该题观察/limitations，而不是反复作为阻断整卷的判题冲突。空白题可确认未作答但原因未知，同样不必阻断选题。只有仍会改变正误、题意或关键解法的未决矛盾才阻断；对确定的考点可用少量练习探索未知环节，不能编造首错来换取通过。


1.2契约每道可读题（包括对题）必须有solution_guide：entry_point说明从哪个具体条件入手以及为何有效；strategy给整体路线；key_steps给足够复核的关键推导，保留必要等式和条件；pitfalls说明本题容易误用的条件、计算或收尾事项。reference_reasoning保存正确解法的核验推导，不能只给答案或一句方法名，也不输出内部思考过程。题干确实缺失时solution_guide可为null并说明具体缺口，不能为凑字段造题意。

错题、部分完成、空白和正误未知题必须写cause_summary，向学生提供高层面的排查思路。先说可见事实及保留的正确环节，再解释为何这些表现可能对应某个操作缺口，必要时列1～3个有区分价值的候选原因到hypotheses，并说明如何在后续作答中辨别。没有推导时，依据本题的必要操作提出候选排查方向，明确“由题目要求提出、尚无原作答支持”，不能把它说成学生已经犯下的错误。不能仅写“原因未知/未附加假设”而不提供学习方向，也不为填满假设强行诊断基础差或心态差。

已确认未作答纳入错题补强：correctness=wrong、student_state=not_attempted、first_error=null；skill_events用incomplete或hypothesis，不写exam_error/exam_success来假装观察到数学操作。若用户将空白概括为“没思路或时间不足”，这是用户自述的可能背景，不能进一步推断两者比例或哪一项是确定原因；解释本题可从哪里入手，选题阶段可探索切入/必要操作。扫描缺页、题意缺失不等于确认空白，仍按材料不足保留未知。

每题先独立理解并核验正确解法，再核对学生步骤；参考解析用于交叉检查。提供可阅读的思路与关键步骤，保留正确部分，定位首个实质性错误及其连锁影响。最终答案与过程有效性分开，不能由终值直接判定全部方法。原卷没有推导时，只保留可能原因，不推断基础、心态或耗时。空白只记未见作答，原因未知；不用逐题追问代替分析。关键图像不可辨时指出具体补拍区域，其余可分析部分继续交付。

可能原因与观察分开，证据不足可为空或未知，不为每个猜测安排练习或要求学生确认。题目指纹描述条件、目标、方法和微操作；学生错因与熟练程度另存。对题也可有待辨析环节，但没有问题证据时不制造检验。

read_skill返回统一knowledge_catalog及只引用现有目录的catalog_policy。关联知识时复用已存在ID和规范数学名称；目录未覆盖则分开记录题目的数学说明与目录缺口，不伪造ID，也不在本轮新增、改名或合并节点。考点树是试卷/错题/练习的证据索引，不把父节点分类当作学生已掌握的证据。原卷分析只按当前契约保存knowledge、fingerprint和skill_events；后续独立organize_knowledge任务维护稳定ID关联，不在分析结果中另造树节点或宣称出处导航已建立关联。

1.3契约中题意可读的题必须提供非空knowledge及fingerprint.methods/operations，包括错题和空白题。考点说明这题考什么，操作说明做成这题需要哪一步；cause_summary说明可见问题及可能原因，未知仍保留。三者共同服务后续选题，不能因无法确认学生为什么错而省略题目考点，也不要求学生补原因；缺页/题意确实缺失时保留材料缺口，不凑标签。面向学生的说明用“未作答”等中文，结构枚举只用于JSON。

用 `apply_report` 的 `{result:完整任务结果JSON}`交付。逐题字段完全依照本任务schema，不另造probes；仅analyze_paper的questions覆盖expected_count全部题号；review_question只交付指定question。regions.bbox是原PDF点坐标，先看read_paper.page_dimensions，不能填渲染图片像素。题干可见但作答模糊时保留可见题目区域；整题缺失才可在partial/needs_material中给空区域。不要覆盖真实作答。CLI仅用agent_tasks.py deliver及原任务write_ticket，旧apply写入已停用。

分析保存后结束本轮，不在本任务里布置练习或询问是否继续。应用派发选题任务时再加载mathlens-bank-search和mathlens-probe-design，按考点、目标环节与观察表现合并目标并结合历史精选练习。每目标1～2道是预算，可为0；一题覆盖多目标不重复布置。尚待核对的初步报告不能作为正式选题依据；原卷局部复核/纯解释不因此重做全卷选题，不用旧probes写法绕过当前任务契约。

教学内容通过固定结构的 report 写回，公式放在相应文字字段中；不能仅在最终聊天里给出解析而不保存。校验失败时按工具反馈修正同一任务的结构，不要求学生整理 JSON；数学未知保持未知，不为过校验编造结论。最终只简要说明本卷已保存内容、关键限制和下一步练习，不发起常规的逐题问答。


整卷分析的初始包已给原卷完整页、expected_count、missing_question_numbers，以及按题号匹配的参考题干/答案/解析和角色回执。缺本地切分的题号仍须包含在报告内，从完整页定位，不删号也不以整页覆盖既有局部。先核对候选与原题条件、目标、选项等价，再将可辨原作答逐题对照参考判正误；参考不是学生作答。只有原作答确实不可辨或参考缺失时才保留unknown，注明具体页、局部/行及缺口。整页看不清先局部放大，不以错因未知替代正误判断。重交时按汇总错误逐项修正，保留事实、转录和核验推导，不把报告逐轮压短。新补题只有整页定位时写“位置待确认”。
