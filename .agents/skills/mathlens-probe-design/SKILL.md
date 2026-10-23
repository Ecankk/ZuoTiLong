---
name: mathlens-probe-design
description: 使用已经允许展示且核对过的题库原题，为一个待验证原因设计分环节检验；不生成新题，不绕过题目查看确认。
---

# 分环节检验

输入原卷观察、竞争原因和已核对的 bank_id。以 context 中的设置及 student_access 为准：仅隐藏当前备考类别的检验候选，其他类别直接显示；本地题库直接浏览。可先保存仍隐藏的检验任务，确认前聊天只给类别、年份和题号，不泄露题干或目标考点。

保留原题条件，按诊断目的选择切入、建模/建系、求导/积分/换元计算或最终处理中的一个环节。明确需要回答什么，以及为何这一回答能区分竞争解释。只改变回答范围，不能悄悄改条件再称为原题。

定义正确、错误或不知道时各支持/削弱哪些解释；写清提示、前提和答案暴露。若同时检验多个环节，说明如何区分，避免失败后仍无法定位。

用 apply_report 的 probes 写回：id、question_number、bank_id、skill_id、skill_label、targets、prompt、discriminates、expected、priority；accepted 仅用于简单无歧义的纯文字答案。discriminates 写清为何选题和怎样区分原因。apply 不覆盖同 ID；用 replace_probe（probe_id、reason、changes）显式替换，保留旧作答与修订版本。

学生提交前不展示预期答案和解析；不要把尚未作答的任务记作失败。优先少量有区分价值的检验，等反馈后再增加。
