---
trigger: always_on
description: Core guidelines and coding standards for the Video Summarization project.
---

# Video Summarization Project Rules

When working on this project, the agent MUST follow these guidelines:

1. **Language & Stack**: 
   - Backend: Python (FastAPI/Scripts).
   - Frontend: Node.js (React/Tailwind).
   - Follow PEP8 for Python, and standard ESLint rules for Node.

2. **Communication**:
   - Keep explanations brief. The user wants to "Get shit done".
   - Use Roman Urdu / English mixed when talking to the user, as preferred by them.

3. **Safe Execution**:
   - Do not delete cache folders (`audio_cache/`, `faiss_index/`) without explicit user permission.
   - Always check `diagnostic.log` or `benchmark.log` for recent errors before making backend logic changes.
