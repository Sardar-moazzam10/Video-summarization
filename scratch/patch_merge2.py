with open('backend/api/merge.py', 'r') as f:
    content = f.read()

content = content.replace(
'''        if acq_token is not None:
            try:
                import asyncio
                task = asyncio.current_task()''',
'''        if acq_token is not None:
            try:
                task = asyncio.current_task()'''
)

content = content.replace(
'''        try:
            import asyncio
            task = asyncio.current_task()''',
'''        try:
            task = asyncio.current_task()'''
)

with open('backend/api/merge.py', 'w') as f:
    f.write(content)
