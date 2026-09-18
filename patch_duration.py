import re
with open('backend/services/coverage_selector.py', 'r') as f:
    content = f.read()

# Replace the block at line 583
new_block = """    if isinstance(total_duration, dict):
        sum_duration = sum(total_duration.values())
    else:
        if total_duration <= 0:
            total_duration = max(float(getattr(s, "end_time", 0.0)) for s in segments) if segments else 0.0
        sum_duration = max(total_duration, 1.0)
    
    capacity = sum_duration / n_bins"""

content = re.sub(
    r'    if isinstance\(total_duration, dict\):\n        sum_duration = sum\(total_duration\.values\(\)\)\n        capacity = sum_duration / n_bins\n    else:\n        if total_duration <= 0:\n            total_duration = max\(float\(getattr\(s, "end_time", 0\.0\)\) for s in segments\) if segments else 0\.0\n        total_duration = max\(total_duration, 1\.0\)\n        capacity = total_duration / n_bins',
    new_block,
    content
)

# Line 610: max(total_duration, 1.0) -> max(sum_duration, 1.0)
content = content.replace('max(total_duration, 1.0),', 'max(sum_duration, 1.0),')

# Line 759: capacity = total_duration / n_bins -> remove it completely!
content = content.replace('        capacity = total_duration / n_bins\n', '')

with open('backend/services/coverage_selector.py', 'w') as f:
    f.write(content)
