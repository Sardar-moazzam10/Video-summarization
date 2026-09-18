import re
with open('backend/services/narrative_sorter.py', 'r') as f:
    content = f.read()

content = content.replace(
    'from .fusion_engine import get_sentence_transformer, CrossEncoder',
    'from .fusion_engine import get_sentence_transformer\n        from sentence_transformers import CrossEncoder'
)

with open('backend/services/narrative_sorter.py', 'w') as f:
    f.write(content)
