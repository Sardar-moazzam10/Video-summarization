import re
with open('backend/services/coverage_selector.py', 'r') as f:
    content = f.read()

content = content.replace(
    '# capacity is already defined',
    'capacity = total_duration / n_bins'
)

with open('backend/services/coverage_selector.py', 'w') as f:
    f.write(content)
