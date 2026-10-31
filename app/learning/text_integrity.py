"""Reject newly introduced non-display controls without guessing TeX repairs."""
import re

INVALID_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
MISSING = object()


def validate_result_text(result, *, legacy_questions=None):
    """Preserve exact frozen revision fields; do not propagate new corruption."""
    legacy_questions = legacy_questions or {}

    def walk(value, path, previous=MISSING):
        if isinstance(value, str):
            match = INVALID_CONTROL.search(value)
            if match and value != previous:
                code = f'U+{ord(match.group()):04X}'
                raise ValueError('结果文字包含不可显示的控制字符：' + path + ' (' + code +
                    ')。请修正该字段的JSON/JS字符串转义；LaTeX反斜杠须保留，不能猜测删除或自动替换。')
        elif isinstance(value, dict):
            for key, item in value.items():
                old = previous.get(key, MISSING) if isinstance(previous, dict) else MISSING
                walk(item, path + '/' + key, old)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                old = previous[i] if isinstance(previous, list) and i < len(previous) else MISSING
                if path == 'result/questions' and isinstance(item, dict):
                    old = legacy_questions.get(item.get('bank_id'), MISSING)
                walk(item, path + '/' + str(i), old)

    walk(result, 'result')
