"""Project-owned stdio MCP: no shell, arbitrary SQL, file paths or network tools."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from learning_tools import execute, SCHEMA, DESCRIPTION


def main():
    data=Path(os.environ.get('MATHLENS_DATA_DIR',ROOT/'.mathlens')).resolve()
    for line in sys.stdin:
        message=None
        try:
            message=json.loads(line);method=message.get('method');params=message.get('params',{})
            if 'id' not in message:continue
            if method=='initialize':result={'protocolVersion':params.get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'mathlens-learning','version':'0.5.0'}}
            elif method=='ping':result={}
            elif method=='tools/list':result={'tools':[{'name':'mathlens','description':DESCRIPTION,'inputSchema':SCHEMA}]}
            elif method=='tools/call':
                if params.get('name')!='mathlens':raise ValueError('未知学习工具')
                args=params['arguments'];result={'content':execute(ROOT,data,args['action'],args.get('payload',{})),'isError':False}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':message['id'],'error':{'code':-32601,'message':'unsupported method'}}),flush=True);continue
            output={'jsonrpc':'2.0','id':message['id'],'result':result}
        except Exception as exc:
            if not message or 'id' not in message:continue
            output={'jsonrpc':'2.0','id':message['id'],'result':{'content':[{'type':'text','text':str(exc)}],'isError':True}}
        print(json.dumps(output,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
