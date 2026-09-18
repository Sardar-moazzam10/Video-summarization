with open('backend/services/coverage_selector.py', 'r') as f:
    content = f.read()

content = content.replace("""
    print(f"[DEBUG] sum_duration type: {type(sum_duration)} value: {sum_duration}")
    if len(concepts):
""", "    if len(concepts):")

with open('backend/services/coverage_selector.py', 'w') as f:
    f.write(content)
