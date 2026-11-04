"""Per-read immutable lookup reuse, scoped to one existing SQLite snapshot."""
from app.knowledge import catalog
from app.bank import annotations


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
        if not self._aliases:
            # The exact same equivalence closure as access.aliases(), built
            # once within this immutable SQLite view instead of scanning every
            # identity/link again for each of thousands of questions.
            parents={};hashes={}
            def find(value):
                parents.setdefault(value,value)
                while parents[value]!=value:
                    parents[value]=parents[parents[value]];value=parents[value]
                return value
            def join(left,right):parents[find(left)]=find(right)
            for row in self.conn.execute('SELECT bank_id,sha256 FROM bank_identity'):
                find(row['bank_id'])
                if row['sha256']:
                    join(row['bank_id'],hashes.setdefault(row['sha256'],row['bank_id']))
            from app.bank.identity_reviews import confirmed_pairs
            for left,right in list(self.conn.execute('SELECT left_id,right_id FROM bank_links'))+confirmed_pairs(self.conn):join(left,right)
            groups={}
            for member in parents:groups.setdefault(find(member),set()).add(member)
            self._aliases={member:group for group in groups.values() for member in group}
        return self._aliases.get(bid,{bid})
