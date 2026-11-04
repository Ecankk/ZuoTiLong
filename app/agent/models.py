"""Local app-server model catalog and explicit task profiles."""
JUDGMENT = {'analyze_paper','review_question','grade_attempt','review_practice','maintain_catalog','annotate_questions'}
DEFAULT_PROFILES = {'judgment': {'model':'gpt-6-luna','effort':'xhigh'},
                    'organization': {'model':'gpt-6-luna','effort':'high'}}

def profiles(value=None):
    result={k:dict(v) for k,v in DEFAULT_PROFILES.items()}
    if value is not None:
        if not isinstance(value,dict) or set(value)-set(result):raise ValueError('模型档位不合法')
        for key,item in value.items():
            if not isinstance(item,dict) or set(item)!={'model','effort'} or any(not isinstance(v,str) or not v.strip() or len(v)>120 for v in item.values()):
                raise ValueError('每个模型档位须包含model和effort')
            result[key]=dict(item)
    return result

def catalog(transport):
    items=[];cursor=None
    while True:
        page=transport.request('model/list',{'limit':100,**({'cursor':cursor} if cursor else {})})
        for item in page.get('data',[]):
            items.append({'id':item['model'],'name':item.get('displayName',item['model']),
                          'efforts':[v['reasoningEffort'] for v in item.get('supportedReasoningEfforts',[])]})
        cursor=page.get('nextCursor')
        if not cursor:return items

def selected(kind,prefs,items):
    key='judgment' if kind in JUDGMENT else 'organization'
    value=profiles(prefs.get('execution_profiles'))[key]
    found=next((m for m in items if m['id']==value['model']),None)
    if not found or value['effort'] not in found['efforts']:
        raise ValueError(f"所选模型/推理强度不可用：{value['model']} / {value['effort']}。请在设置中选择本机可用项。")
    return dict(value,profile=key)
