---
name: mathlens-learning-update
description: 按 MathLens 本次布置范围批改已提交的真实练习，分开数学事实、可能原因和提示证据，或聚合已保存记录总结本卷；不代写学生作答。
---

# 练习批改与证据总结

先读 context.learning_task.result_schema。grade_attempt 用 assess，summarize_paper 用 apply_report，payload 均为 `{result:完整任务封装}`；CLI仅用 agent_tasks.py deliver 及本任务票据。按固定字段交付并取得回执，不退回旧assessment/findings格式、不直接写库或在聊天另写一套能力报告。

## 批改本次作答

用 read_attempt(attempt_id) 获取真实文字、按顺序的照片、角色和probe。先明确 probe.prompt 所限定的本次回答范围和目的；按其中 bank_id 用 read_bank 读本任务原题、必要图和参考解析。不能只照抄 expected/solution_note，也不能将其他轮次附件当本次作答。没有真实提交不模拟回答；暂存照片不等于正式批改任务。

契约1.9的read_bank自动读取本attempt固定材料，role=all返回可用题干/参考；不要自行换到题库最新版本。grading_knowledge列出不可用参考，题干完整时可独立求解并说明参考限制；题干关键内容缺失则保留作答、说明材料问题，不改批另一题或让学生转录参考。所引topic_ids须用task_context读取本任务捕获定义，不能凭名称编造。旧契约按原输入工作，不补字段或新绑定。

共享标注仅供知识关联定位，不是本机解法或学生证据；即使索引后来停用，已布置题仍按本attempt固定材料核验，不改读最新库，也不凭索引原子列表判全对/全错。

先独立解出本次所需结论，再逐步检查学生的实际过程，参考解析只作交叉核验。按本次布置环节评分：未要求的小问或后续步骤不算漏做；题库参考答案覆盖整题时，仍只评价已布置范围。区分答案、过程和目标环节，保留正确部分，定位首个实质性错误，后续连锁结果不重复归因。终值错不等于方法错，终值对不等于推导有效。

按 image_roles 区分 own_work 原作答、external_solution 外部解析、marking 事后批改；外部资料不是学生推导。看不清关键步骤或只有外部图时，correct=null，并在 needs_material 明确需补拍的区域，不猜补、不要求整页转录或重做整卷。文字明确写“不知道”是可评价的真实回答，不当成图片缺失。

看题干、看答案/解析、正式提交是不同事件。沿用记录里的提示/曝光和作答版本，提交后再查看解析不否定先前独立版本；看解析后补写的部分不冒充新独立成功。缺少耗时/心态证据时保留未知。

按schema填写 feedback/reference_reasoning/observations/first_error/possible_causes/topic_ids/next_step/needs_material：反馈要有本次检查的推导和改进方向；观察写实际步骤，可能原因保留证据限制。没有首错可为null，材料不足不能强判。topic_ids只能引用read_skill提供的knowledge_catalog现有稳定ID，仅填写本次有依据的知识范围；目录缺口写入可用的说明字段并保留未知，不在批改中新增或改名考点；未核实的相关知识不要一并判失败。原题原因假设留在原证据，保存和远端结束后由独立knowledge-index阶段关联长期目录，画像按有效证据聚合，不直接重写能力评分。

重新批改使用当前任务和作答版本，旧反馈保留、不重复累计。同题跨目标只评价同一attempt，不因显示多处复制评价；一次成功不足以宣称稳定掌握。批改结束即结束本轮，不自行重跑整卷或自动追加练习，追加由应用单独派发准备任务。

## 总结本卷

summarize_paper 只聚合已保存的原卷分析、练习和批改，从 allowed_source_refs 选择真实引用。key_findings/improvements 的 evidence_refs 必须在 source_refs 中；改善须有前后证据，没有就空数组，建议放 next_focus。不能重新解原卷造另一套诊断或新增作答/掌握事件。

如实区分未做、待批改、需补拍、已反馈和未知；保留未做练习，不把未完成当失败或强制清空。仍隐藏候选只写允许显示的出处，不在总结泄题。知识索引只组织已保存的证据；尚未落库的结束轮次不能冒称已完成。

可用 memory_read/memory_write 维护 index.md 短索引：事实、假设、证据引用、修订依据和下次复测目标分开。个人内容不放公开AGENTS/Skill；只有真实写入成功才能说已保存，不将记忆笔记当新增学习证据。
