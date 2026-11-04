"""Fixed role methods, supplied as task material rather than Codex skill discovery."""
SKILLS=('paper-diagnosis','bank-search','probe-design','learning-update','knowledge-index','catalog-maintenance','question-topics')
ROLE_SKILLS={'analyze_paper':('paper-diagnosis',),'review_question':('paper-diagnosis',),
    'grade_attempt':('learning-update',),'summarize_paper':('learning-update',),
    'prepare_practice':('bank-search','probe-design'),'organize_knowledge':('knowledge-index',),
    'maintain_catalog':('catalog-maintenance',),'annotate_questions':('question-topics',),
    'review_practice':('probe-design',)}

def skill_name(payload):
    name=payload.get('name')
    if not isinstance(name,str) or name.removeprefix('mathlens-') not in SKILLS or set(payload)!={'name'}:
        raise ValueError('read_skill参数为{name:"mathlens-knowledge-index"}；合法名称：'+', '.join('mathlens-'+n for n in SKILLS))
    return name.removeprefix('mathlens-')

def body(root,name):
    return (root/'.agents/skills'/('mathlens-'+name)/'SKILL.md').read_text(encoding='utf-8')

def for_kind(root,kind):
    return {'kind':kind,'skill_names':['mathlens-'+n for n in ROLE_SKILLS[kind]],
        'skills':[{'name':'mathlens-'+n,'instructions':body(root,n)} for n in ROLE_SKILLS[kind]],
        'execution_override':'方法正文中的context、read_skill及材料阅读步骤，已由本包实际提供的材料与后端回执完成；不要为凑回执重复读取。标明材料齐全时直接deliver_result({result:完整封装})，仅校验报错或实际缺少材料时补读/修正，不例行preflight。'}
