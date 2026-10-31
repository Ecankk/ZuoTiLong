"""Preserve selected bindings while admitting explicitly imported provenance."""
import re


def migrate(conn):
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='practice_question_bindings'").fetchone()
    if not row or not any(r[2] == 'question_annotations' for r in conn.execute('PRAGMA foreign_key_list(practice_question_bindings)')):
        return {'changed_tables': []}
    if conn.in_transaction:
        raise ValueError('标注出处迁移只能在启动的独立事务中执行')
    before = {tuple(r) for r in conn.execute('PRAGMA foreign_key_check')}
    enabled = conn.execute('PRAGMA foreign_keys').fetchone()[0]
    conn.execute('PRAGMA foreign_keys=OFF')
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('CREATE TABLE IF NOT EXISTS prepared_annotation_ids(id TEXT PRIMARY KEY)')
        conn.execute('INSERT OR IGNORE INTO prepared_annotation_ids(id) SELECT id FROM question_annotations ORDER BY rowid')
        sql, count = re.subn(r'REFERENCES\s+question_annotations\s*\(id\)',
                            'REFERENCES prepared_annotation_ids(id)', row[0], flags=re.I)
        if count != 1:
            raise ValueError('练习标注引用结构不符合已知迁移版本')
        name = '_annotation_origin_bindings'
        if conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name,)).fetchone():
            raise ValueError('发现未识别的标注迁移临时表，未覆盖')
        sql, count = re.subn(r'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?practice_question_bindings["`\]]?',
                            'CREATE TABLE ' + name, sql, count=1, flags=re.I)
        if count != 1:
            raise ValueError('练习绑定建表语句无法安全迁移')
        extra = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE tbl_name='practice_question_bindings' AND type IN ('index','trigger') AND sql IS NOT NULL")]
        columns = ','.join('"' + r[1].replace('"', '""') + '"' for r in conn.execute('PRAGMA table_info(practice_question_bindings)'))
        conn.execute(sql)
        conn.execute('INSERT INTO ' + name + '(rowid,' + columns + ') SELECT rowid,' + columns + ' FROM practice_question_bindings')
        conn.execute('DROP TABLE practice_question_bindings')
        conn.execute('ALTER TABLE ' + name + ' RENAME TO practice_question_bindings')
        for sql in extra:
            conn.execute(sql)
        if {tuple(r) for r in conn.execute('PRAGMA foreign_key_check')} != before:
            raise ValueError('标注出处迁移引用核验失败，已回滚')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute('PRAGMA foreign_keys=' + ('ON' if enabled else 'OFF'))
    return {'changed_tables': ['practice_question_bindings'], 'preserved_reference_issues': len(before)}
