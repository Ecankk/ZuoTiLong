import json,sqlite3
from app.common import now_iso

def seed(conn: sqlite3.Connection) -> None:
    created = now_iso()
    papers = [
        ("paper-demo-2022", "真题 2022（示例）", "2026-10-21", 101, 150, 136, "真题2022.pdf", "needs_review"),
        ("paper-demo-2021", "真题 2021（示例）", "2026-10-17", 96, 150, 142, "真题2021.pdf", "analyzed"),
    ]
    conn.executemany(
        "INSERT INTO papers(id,title,exam_date,score,total_score,duration,source_name,import_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [p + (created, created) for p in papers],
    )
    questions = [
        ("q-demo-01", "paper-demo-2022", "18", "高数", "含参数定积分的换元与上下限处理", 4, 5, "partial", "待诊断", None, None, "定积分｜换元｜上下限联动", json.dumps({"objects":["定积分"],"entry_cues":["复合函数"],"method":["换元积分"],"operations":["上下限同步变换"],"final_checks":["符号","上下限"]}, ensure_ascii=False), "做出了主体步骤，但换元后上下限漏改", created),
        ("q-demo-02", "paper-demo-2022", "19", "线代", "二次型正定性与正交变换", 2, 5, "wrong", "待诊断", None, None, "二次型｜特征值｜正定性", json.dumps({"objects":["二次型","特征值"],"entry_cues":["正定"],"method":["特征值判断"],"operations":["矩阵运算"],"final_checks":["特征值符号"]}, ensure_ascii=False), "不会从题目条件判断切入方法", created),
        ("q-demo-03", "paper-demo-2022", "20", "概率", "分布函数与数字特征", 5, 5, "correct", "高风险正确", None, None, "分布函数｜数字特征", json.dumps({"objects":["分布函数"],"entry_cues":["分段分布"],"method":["数字特征公式"],"operations":["分段积分"],"final_checks":["定义域"]}, ensure_ascii=False), "答对但用时 18 分钟且自信度低", created),
        ("q-demo-04", "paper-demo-2021", "17", "高数", "多元函数极值的条件判断", 0, 5, "wrong", "已复盘", "建模与路径", "方法不会", "多元函数｜极值｜条件判断", json.dumps({"objects":["多元函数极值"],"entry_cues":["约束条件"],"method":["拉格朗日乘子"],"operations":["方程组"],"final_checks":["候选点筛选"]}, ensure_ascii=False), "忽略了约束条件", created),
        ("q-demo-05", "paper-demo-2021", "22", "概率", "二维随机变量边缘分布", 3, 5, "partial", "训练中", "中间计算", "计算失误", "二维随机变量｜边缘分布", json.dumps({"objects":["二维随机变量"],"entry_cues":["联合分布"],"method":["边缘化"],"operations":["积分区间"],"final_checks":["区域边界"]}, ensure_ascii=False), "积分区域边界漏项", created),
    ]
    conn.executemany(
        """INSERT INTO questions(id,paper_id,number,subject,stem,score_earned,max_score,correctness,review_status,error_stage,error_type,knowledge,fingerprint_json,notes,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        questions,
    )
    bank = [
        ("bank-calc-01", "本地示例题库", "calc-01", "定积分换元：给定复合函数，判断换元变量与上下限", "按新变量同步修改上下限", "先写换元关系，再检查上下限与符号。", ["定积分","换元","上下限联动"], {"objects":["定积分"],"method":["换元积分"],"stages":["切入","计算"]}, 2),
        ("bank-calc-02", "本地示例题库", "calc-02", "参数积分：换元后保留参数并判断积分区间", "分情况讨论参数范围", "关键是先确定变量范围，再写积分上下限。", ["定积分","参数","换元"], {"objects":["定积分"],"method":["换元积分"],"stages":["切入","最终处理"]}, 3),
        ("bank-calc-03", "本地示例题库", "calc-03", "积分区域变换：用极坐标计算二重积分", "先画区域再换元", "区域边界决定上下限，不能直接套公式。", ["重积分","换元","区域"], {"objects":["重积分"],"method":["极坐标"],"stages":["建模","计算"]}, 3),
        ("bank-linear-01", "本地示例题库", "linear-01", "二次型正定性：由特征值符号判断", "所有特征值为正", "先识别正定性，再选择顺序主子式或特征值。", ["二次型","特征值","正定性"], {"objects":["二次型"],"method":["特征值判断"],"stages":["切入","最终处理"]}, 2),
        ("bank-linear-02", "本地示例题库", "linear-02", "二次型正交变换：构造标准形", "正交矩阵列为单位特征向量", "注意特征向量的单位化和顺序。", ["二次型","正交变换"], {"objects":["二次型"],"method":["正交变换"],"stages":["建模","中间计算"]}, 3),
        ("bank-linear-03", "本地示例题库", "linear-03", "含参数矩阵的特征值判断", "按参数范围讨论", "参数变化会改变正定性结论。", ["特征值","参数","正定性"], {"objects":["特征值"],"method":["特征值判断"],"stages":["切入","最终处理"]}, 4),
        ("bank-prob-01", "本地示例题库", "prob-01", "已知分布函数求概率与密度", "先分段再积分", "先写定义域和连续性边界。", ["分布函数","密度"], {"objects":["分布函数"],"method":["分段积分"],"stages":["切入","最终处理"]}, 2),
        ("bank-prob-02", "本地示例题库", "prob-02", "联合密度求边缘密度", "对另一变量积分", "先画积分区域，避免漏掉边界。", ["二维随机变量","边缘分布"], {"objects":["二维随机变量"],"method":["边缘化"],"stages":["建模","中间计算"]}, 3),
        ("bank-prob-03", "本地示例题库", "prob-03", "数字特征综合计算", "分别计算期望与方差", "注意方差平方项和分布范围。", ["数字特征","期望","方差"], {"objects":["数字特征"],"method":["数字特征公式"],"stages":["中间计算","最终处理"]}, 2),
        ("bank-calc-04", "本地示例题库", "calc-04", "中值定理：判断可用条件并定位结论", "先核对闭区间连续与开区间可导", "条件不完整时不能直接套结论。", ["中值定理","条件判断"], {"objects":["中值定理"],"method":["条件判断"],"stages":["切入","最终处理"]}, 2),
    ]
    conn.executemany(
        """INSERT INTO bank_questions(id,source,source_ref,stem,answer,explanation,tags_json,fingerprint_json,difficulty,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [(a,b,c,d,e,f,json.dumps(g,ensure_ascii=False),json.dumps(h,ensure_ascii=False),i,created) for a,b,c,d,e,f,g,h,i in bank],
    )
