---
name: mathlens-bank-search
description: 在 MathLens 本地题库中为某个错误原因寻找检验题，阅读原题并说明取舍；遵守用户数学类别和展示限制，不把分类匹配当作教学判断。
---

# 检验题检索

先明确 paper_id/question_id、待检验的微技能和竞争解释。通过 `mathlens` 的 context 读取用户 study_type、mask_same_type、reserved 和确认记录，不自行指定预留年份。

优先用 `catalog`（topics、math_types、years、exclude_years、bank_id、offset、limit）浏览，再用 `read_bank` 直接阅读原图和相关解析。三类题库统一支持；显式预留卷不进入 Agent 候选和 read_bank，用户仍可自主浏览本地题库。独立 CLI 对应 `scripts/agent_tasks.py catalog --math-type 2 --topic <分类>`。目录分类和图片完整不等于数学结论已核验。

检索范围与学习类别分开：候选目标覆盖数一、二、三，跨类别仍须检查目标环节是否适合当前学生，不向其强加额外前置内容。

本地题库由用户直接浏览，不做题干隐藏。试卷的针对性检验才按设置隐藏：mask_same_type 开启时，study_type 对应类别的未确认候选只给“类别、年份、题号”；其他类别直接展示，不要求先完成跨类别核对。关闭开关则全部直接展示。以 student_access.can_view 为当前依据，不复述仍隐藏候选的题干、考点或目标环节。明确预留卷不用于 Agent 选题。

在用户允许的范围内阅读原题及相关解析，核对目标结论。以自然语言解释每道候选针对的原因、所需前提和可取的回答范围；不使用固定相似度/排名替代判断。没有合适的题就记录缺口。

跨类别阅读仍需判断目标环节是否适合学生。发现同题可用 review_cross 的 other_id、distinct=false 保存关联，以复用阅读与答案曝光记录；它是可选记录，不是其他类别直接展示的前置关卡。同题关联不改变用户按类别设置的显示规则。

用 memory_write 保存 `bank/<bank_id>.json` 阅读笔记，包含 ID、来源、图像散列、核对范围与未决问题。路径列表不算已阅读。不要把内部候选正文写进最终回复。
