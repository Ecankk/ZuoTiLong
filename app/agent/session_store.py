"""Atomic persistence of the local projection of the one remote session."""
import json,sqlite3
from contextlib import closing

class SessionStore:
    def __init__(self,path):self.path=path
    def load(self):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('CREATE TABLE IF NOT EXISTS session(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            saved=conn.execute('SELECT payload FROM session WHERE id=1').fetchone()
        state=json.loads(saved[0]) if saved else {'session_id':None,'turns':[],'active_request':None}
        state['revision']=self._revision(state)
        return state

    @staticmethod
    def _revision(state):
        value=state.get('revision',0)
        return value if type(value) is int and value>=0 else 0

    def save(self,state):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT payload FROM session WHERE id=1').fetchone()
            previous=json.loads(row[0]) if row else {}
            saved={**state,'revision':max(self._revision(state),self._revision(previous))+1}
            from app.learning.loop import stamp
            saved['updated_at']=stamp()
            conn.execute('INSERT OR REPLACE INTO session VALUES(1,?)',(json.dumps(saved,ensure_ascii=False),))
        state.update(revision=saved['revision'],updated_at=saved['updated_at'])
