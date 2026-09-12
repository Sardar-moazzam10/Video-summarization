with open('/home/weiblocks/Desktop/Video-summarization/backend/main.py', 'r') as f:
    content = f.read()

old_code = """    # Record request
    rate_limit_store[client_ip].append(current_time)

    return await call_next(request)
    try:
        return await call_next(request)
    except Exception as e:
        raise
    except BaseException as e:
        import asyncio
        if isinstance(e, asyncio.CancelledError):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=499, content={"detail": "Client Closed Request"})
        raise"""

new_code = """    # Record request
    rate_limit_store[client_ip].append(current_time)

    try:
        return await call_next(request)
    except BaseException as e:
        import asyncio
        if isinstance(e, asyncio.CancelledError):
            return JSONResponse(status_code=499, content={"detail": "Client Closed Request"})
        raise"""

content = content.replace(old_code, new_code)

with open('/home/weiblocks/Desktop/Video-summarization/backend/main.py', 'w') as f:
    f.write(content)

print("patched")
