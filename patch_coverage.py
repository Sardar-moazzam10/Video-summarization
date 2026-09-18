import re
with open('backend/services/coverage_selector.py', 'r') as f:
    content = f.read()

content = content.replace(
"""if isinstance(total_duration, dict):
        sum_duration = sum(total_duration.values())
        capacity = sum_duration / n_bins
    else:""",
"""    if isinstance(total_duration, dict):
        sum_duration = sum(total_duration.values())
        capacity = sum_duration / n_bins
    else:"""
)
with open('backend/services/coverage_selector.py', 'w') as f:
    f.write(content)
