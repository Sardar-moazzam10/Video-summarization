---
name: get-shit-done
description: Aapke Video Summarization project ke liye custom workflows aur automation scripts. Isko use karein jab bhi code test, build, ya deploy karna ho.
---

# 🚀 Get Shit Done (Custom Skill)

Aapke dost ka recommended "Get shit done" ab haqeeqat mein is project ka hissa hai! 
Yeh skill Antigravity ko sikhata hai ke is **Video-summarization** project mein tezi se kaam kaise karna hai.

## 🛠️ Workflows

Jab bhi user "get shit done" ya project run/test karne ka kahe, in steps ko follow karein:

### 1. Backend Testing
- Run Python tests using `pytest tests/`
- Check logs in `diagnostic.log` or `benchmark.log` if things fail.

### 2. Frontend Checks
- Project has a `package.json` with React/Tailwind. 
- Run `npm run lint` or `npm test` if working on UI changes.

### 3. Docker & Deployment
- Use `docker-compose up -d` to spin up the local environment.
- If dependencies change, run `pip install -r requirements.txt` for backend.

## 💡 Notes for Agent
- Always verify the `.env` file exists (copy from `.env.example` if missing).
- Keep responses concise and action-oriented. Less talk, more code!
