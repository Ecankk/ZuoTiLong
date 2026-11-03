"""Reject transport role names in prose intended for students."""
import re

INTERNAL_ROLES=re.compile(r'\b(?:own_work|external_solution|marking)\b',re.I)

def validate_student_text(value):
    if isinstance(value,dict):
        for child in value.values():validate_student_text(child)
    elif isinstance(value,list):
        for child in value:validate_student_text(child)
    elif isinstance(value,str) and INTERNAL_ROLES.search(value):
        raise ValueError('面向学生的批改文字请使用“你的作答”“事后批改”“参考解析”，不要使用内部附件角色名')
