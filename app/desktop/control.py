from contextvars import ContextVar
import json
import logging
import threading
from app.desktop.protocol import PROTOCOL,Cancelled

CANCEL=ContextVar('desktop_startup_cancel',default=None)


def checkpoint():
    event=CANCEL.get()
    if event is not None and event.is_set():raise Cancelled('已取消')


class ParentControl:
    def __init__(self,stream,nonce):
        self.stream,self.nonce=stream,nonce;self.stop=threading.Event();self.on_stop=None

    def request_stop(self):
        self.stop.set()
        if self.on_stop:self.on_stop()

    def start(self):
        self.thread=threading.Thread(target=self.read,name='desktop-parent-stdin',daemon=True);self.thread.start()

    def read(self):
        try:
            while True:
                line=self.stream.readline(4097)
                if not line:self.request_stop();return
                if len(line.encode('utf8'))>4096:
                    while line and not line.endswith('\n'):line=self.stream.readline(4097)
                    logging.warning('control_invalid: input too long');continue
                try:value=json.loads(line)
                except ValueError:value=None
                if not isinstance(value,dict) or value!={'protocol':PROTOCOL,'command':'shutdown','nonce':self.nonce}:
                    logging.warning('control_invalid: expected shutdown with current nonce');continue
                self.request_stop();return
        except (OSError,ValueError):self.request_stop()
