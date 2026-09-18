import re
with open('backend/services/coverage_selector.py', 'r') as f:
    content = f.read()

debug_print = """
    print(f"[DEBUG] sum_duration type: {type(sum_duration)} value: {sum_duration}")
    if len(concepts):
"""
content = content.replace('    if len(concepts):', debug_print)

with open('backend/services/coverage_selector.py', 'w') as f:
    f.write(content)
