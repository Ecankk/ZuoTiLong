"""Allow catalogue/bank tasks without inventing a student paper.

Runs at database startup on a connection with no transaction. Existing rows,
rowids, indexes, triggers and referencing tables retain their identities.
"""
import re

TABLES = ('learning_tasks', 'learning_results', 'workflow_jobs')


def migrate(conn):
    targets = []
    for name in TABLES:
        columns = list(conn.execute('PRAGMA table_info(' + name + ')'))
        if any(row[1] == 'paper_id' and row[3] for row in columns):
            targets.append(name)
    if not targets:return {'changed_tables': []}
    if conn.in_transaction:
        raise ValueError('任务作用域迁移只能在启动时的独立事务执行')
    previous_issues = {tuple(row) for row in conn.execute('PRAGMA foreign_key_check')}
    enabled = conn.execute('PRAGMA foreign_keys').fetchone()[0]
    conn.execute('PRAGMA foreign_keys=OFF')
    try:
        conn.execute('BEGIN IMMEDIATE')
        for name in targets:
            original = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
            altered, n = re.subn(r'\bpaper_id\s+TEXT\s+NOT\s+NULL\b', 'paper_id TEXT', original, flags=re.I)
            if n != 1:raise ValueError('任务表结构不符合已知迁移版本，未更改原库')
            temporary = '_scope_migration_' + name
            if conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (temporary,)).fetchone():
                raise ValueError('发现未识别的迁移临时表，未覆盖')
            altered, n = re.subn(r'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?' + re.escape(name) + r'["`\]]?',
                                 'CREATE TABLE ' + temporary, altered, count=1, flags=re.I)
            if n != 1:raise ValueError('任务表创建语句无法安全迁移')
            dependents = [row[0] for row in conn.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL", (name,))]
            names = [row[1] for row in conn.execute('PRAGMA table_info(' + name + ')')]
            quoted = ','.join('"' + column.replace('"', '""') + '"' for column in names)
            conn.execute(altered)
            conn.execute('INSERT INTO ' + temporary + '(rowid,' + quoted + ') SELECT rowid,' + quoted + ' FROM ' + name)
            conn.execute('DROP TABLE ' + name)
            conn.execute('ALTER TABLE ' + temporary + ' RENAME TO ' + name)
            for sql in dependents:conn.execute(sql)
        if {tuple(row) for row in conn.execute('PRAGMA foreign_key_check')} != previous_issues:
            raise ValueError('任务作用域迁移引用检查未通过，已回滚')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute('PRAGMA foreign_keys=' + ('ON' if enabled else 'OFF'))
    return {'changed_tables': targets,'preserved_legacy_reference_issues':len(previous_issues)}
