---
title: CartPilot API
emoji: 🛍️
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: LangGraph sales agent API for the CartPilot streetwear store
---

# CartPilot agent API

FastAPI + LangGraph sales agent (Claude Haiku 5.5). Endpoints:

- `POST /chat` with `{"user_id": "...", "thread_id": "...", "message": "..."}`
- `GET /health` returns `ok`
- `GET /docs` for interactive API docs

Source code: see the project's GitHub repository.
