---
name: mathlens-paper-diagnosis
description: 在 MathLens 中分析已完成试卷或一道原卷题，基于题干、作答与批改定位最早错误和竞争性原因；不用于题库选题或开发代码。
---

# 原卷诊断

从网页上下文取得 paper_id/question_id。优先用内置 `mathlens` 工具的 `context` 和 `read_paper` 读取历史、原卷和切分草稿；read_paper 每次最多 4 页。页面快照不是用户作答。独立 CLI 可用 `scripts/agent_tasks.py context --paper <paper_id>`。

区分题干、独立作答、考试中自查修正、事后批改及已给提示；笔迹含义遵循这位用户明确说明，不能跨卷自行推广。先指出已完成的正确步骤，再定位最早可见错误。原卷没有推导时，只保留待验证原因，不从一个最终答案推断基础、心态或耗时。

每个待查原因写清：观察证据、竞争解释、能区分两者的最小检验。题目指纹描述条件、目标、方法和微操作；学生错因与熟练程度另存。对题也可有待辨析环节，但没有问题证据时不制造检验。

用 `apply_report` 写回完整报告，payload 为 `{paper_id,report}`：report 包含 author、method、source_sha256、expected_count、questions、probes；每道 question 包含 number、stem、regions（page、bbox、role）、observation、fingerprint、hypotheses 和 skill_events。questions 覆盖整卷；证据坐标以 PDF 点计。只分析一题时先保留本卷其他已核对记录，不用局部报告覆盖全卷。详细字段见 docs/agent-workflow.md，独立 CLI 可用 agent_tasks.py apply。不要覆盖真实作答或重复累计事件。涉及选题再加载 mathlens-bank-search，本技能不自行展示隐藏候选。

最终用中文和 LaTeX 给出本卷重点、已确认事实、待查原因和下一步。需补充说明时只问影响结论的问题，并结束该轮。
