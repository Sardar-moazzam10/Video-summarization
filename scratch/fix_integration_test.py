import re
with open('backend/tests/test_acquisition_observability.py', 'r') as f:
    c = f.read()
if 'job.style = "concise"' not in c:
    c = c.replace('job.target_duration_minutes = 5.0', 'job.target_duration_minutes = 5.0\\n    job.style = "concise"')
with open('backend/tests/test_acquisition_observability.py', 'w') as f:
    f.write(c)
