"""A small, versioned study index, not a claim about the latest exam syllabus."""
VERSION = 'math1-core-2026-10'
REFERENCE = {
    'title': '数学一基础学习目录（项目整理）', 'version': VERSION,
    'reference_url': 'https://yzst.chsi.com.cn/kyzx/math/201210/20121010/348223905.html',
    'reference_date': '2012-10-10', 'checked_at': '2026-10-26',
    'status': '参考研招网历史范围说明组织的粗目录；并非当年官方考纲全文或范围认证。细节点须有题目证据。',
}
CHAPTERS = {
    'calculus': ('高等数学', [
        ('functions-limits', '函数、极限与连续'), ('differentiation', '一元函数微分学'),
        ('integration', '一元函数积分学'), ('geometry', '向量代数与空间解析几何'),
        ('multivariable', '多元函数微分学'), ('multiple-integrals', '重积分'),
        ('line-surface-integrals', '曲线积分与曲面积分'), ('series', '无穷级数'),
        ('differential-equations', '常微分方程')]),
    'linear-algebra': ('线性代数', [
        ('determinants', '行列式'), ('matrices', '矩阵'), ('vectors', '向量组'),
        ('linear-systems', '线性方程组'), ('eigenvalues', '特征值与特征向量'), ('quadratic-forms', '二次型')]),
    'probability': ('概率论与数理统计', [
        ('events', '随机事件与概率'), ('random-variables', '随机变量及其分布'),
        ('joint-distributions', '多维随机变量及其分布'), ('moments', '随机变量的数字特征'),
        ('limit-theorems', '大数定律与中心极限定理'), ('sampling', '数理统计的基本概念与抽样分布'),
        ('estimation', '参数估计'), ('testing', '假设检验')]),
}


def seeds():
    for section, (name, children) in CHAPTERS.items():
        parent = 'math1.' + section
        yield parent, None, name
        for key, label in children:
            yield parent + '.' + key, parent, label
