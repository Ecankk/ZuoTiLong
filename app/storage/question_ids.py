"""Question primary keys need not encode the displayed question number."""
import uuid


def available_question_id(conn, candidate):
    value = candidate
    while conn.execute('SELECT 1 FROM questions WHERE id=?', (value,)).fetchone():
        value = candidate + '-' + uuid.uuid4().hex[:10]
    return value
