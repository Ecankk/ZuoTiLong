import json
import os
import sys
import threading

PROTOCOL='mathlens.desktop/v1'


class DesktopError(RuntimeError):
    def __init__(self,code,message,exit_code=20):
        super().__init__(message);self.code=code;self.exit_code=exit_code


class Cancelled(RuntimeError):pass


class Protocol:
    def __init__(self,operation,nonce,stream=None):
        self.operation,self.nonce,self.stream=operation,nonce,stream or sys.stdout
        self.seq=0;self.lock=threading.Lock();self.phase='validate_config';self.broken=False;self.on_disconnect=None

    def emit(self,event,**fields):
        with self.lock:
            if self.broken:return
            self.seq+=1
            value=dict(protocol=PROTOCOL,event=event,operation=self.operation,seq=self.seq,nonce=self.nonce,pid=os.getpid(),phase=self.phase)
            value.update(fields)
            try:
                self.stream.write(json.dumps(value,ensure_ascii=False)+'\n');self.stream.flush()
            except BrokenPipeError:
                self.broken=True
                if self.stream is sys.stdout:
                    try:self.stream.close()
                    except BrokenPipeError:pass
                    sys.stdout=open(os.devnull,'w',encoding='utf8')
                if self.on_disconnect:self.on_disconnect()

    def progress(self,phase,message,**fields):
        self.phase=phase;fields.setdefault('progress',None)
        self.emit('progress',status='running',message=message,**fields)
