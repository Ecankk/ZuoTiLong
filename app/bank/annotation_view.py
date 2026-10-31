"""Per-read immutable lookup reuse, scoped to one existing SQLite snapshot."""
from app.knowledge import catalog
from app.bank import annotations
from app.bank.access import aliases


class AnnotationReadView:
    def __init__(self,conn,data):
        if not conn.in_transaction:raise ValueError('标注读取复用必须位于明确的只读快照内')
        self.conn,self.data=conn,data
        self.changes=conn.total_changes
        self.release=catalog.document(conn)
        self.nodes={n['id']:n for n in self.release['document']['nodes']} if self.release else {}
        self.redirects={r['old_id']:r['target_id'] for r in self.release['document']['redirects']} if self.release else {}
        self._materials={};self._aliases={}

    def resolve(self,tid):return tid if tid in self.nodes else self.redirects.get(tid)

    def validate(self):
        if not self.conn.in_transaction or self.conn.total_changes!=self.changes:
            raise ValueError('标注只读快照已结束或包含写入，不能继续复用校验')

    def materials(self,bid):
        if bid not in self._materials:self._materials[bid]=annotations.materials(self.conn,self.data,bid)
        return self._materials[bid]

    def aliases(self,bid):
        if bid not in self._aliases:
            group=aliases(self.conn,bid)
            for member in group:self._aliases[member]=group
        return self._aliases[bid]
