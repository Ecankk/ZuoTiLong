"""Keep dynamic-tool images multimodal; never JSON-encode them into inputText."""
def response(content):
    items=[]
    for item in content:
        if item['type']=='text':items.append({'type':'inputText','text':item['text']})
        elif item['type']=='image':items.append({'type':'inputImage','imageUrl':f"data:{item['mimeType']};base64,{item['data']}"})
        else:raise ValueError('不支持的工具内容类型')
    return {'success':True,'contentItems':items}
