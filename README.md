# Content Engine

A FastAPI service for AI content-style cloning. It exports a Telegram channel's posts, analyzes the author's writing style into a reusable profile, and generates new on-style content with Gemini.

## Features

- **Channel export** — pulls posts from any Telegram channel/chat via Telethon, saving a structured JSON export plus a Markdown "vault" (one file per post with front-matter, wiki-links and an index) suitable for Obsidian.
- **Style analysis** — computes rich statistics (length distribution, emoji/hashtag/link usage, top words, structural patterns such as openings, closings and CTAs) and runs a deep LLM analysis to produce a human-readable style guide (voice, lexicon, post formulas, stop-list) plus a JSON profile.
- **On-style generation** — writes new posts that imitate the author, driven by the style guide, statistical metrics and reference posts. Supports post types (informational, story, sales, opinion, list, tutorial), multiple variants, custom tone and extra instructions.
- **Full pipeline** — a single endpoint chains export → analyze → generate as a background task.
- **Background tasks + status polling** — long-running export/pipeline jobs run in the background and are tracked by task ID.

## Tech stack

- Python 3.11+, `asyncio`
- FastAPI + Uvicorn
- Telethon (Telegram MTProto client)
- Google Gemini (via `google-generativeai` REST) as the generation/analysis model
- `httpx`, `pydantic`

## Setup

```bash
pip install fastapi uvicorn telethon httpx pydantic

cp .env.example .env   # then configure the values below
```

The service expects a few working directories (created/used at `/root/content-engine/` by default — adjust in `server.py` / `scripts/` for your environment):

- `exports/` — JSON exports
- `styles/` — generated `*_profile.json` and `*_style.md`
- `vault/` — Markdown post vaults

Run it:

```bash
python server.py
```

The API listens on port `8608` by default (`CONTENT_ENGINE_PORT`).

## API

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET`  | `/health` | Status + list of exported channels and styles |
| `POST` | `/export` | Export a channel (`{channel, limit, account, since_days}`) — background task |
| `POST` | `/analyze` | Analyze an exported channel's style (`{channel_name, json_path?}`) |
| `POST` | `/generate` | Generate on-style posts (`{channel_name, topic, post_type, count, tone?, extra_instructions?}`) |
| `POST` | `/pipeline` | Export → analyze → generate in one background task |
| `GET`  | `/task/{task_id}` | Poll a background task's status/result |
| `GET`  | `/styles` | List analyzed channel styles |

The CLI scripts can also be run standalone:

```bash
python scripts/tg_export.py @channel 200 1 30           # channel limit account since_days
python scripts/style_analyzer.py exports/Channel.json
python scripts/content_generator.py "Channel" "topic" list 3
```

## Notes

- **External dependency:** the analyzer and generator import a shared `ai_helper` module (expected at `/root/ai_helper.py`, providing `call_ai` / `call_ai_vision`) as the primary AI backend, with a direct Gemini REST call as fallback. Provide this module or replace the import to run standalone.
- **Telegram credentials:** Telethon `API_ID` / `API_HASH` are set in `scripts/tg_export.py`, and the session string is read from `TG_SESSION_STRING[_N]` (checked in `/root/claudeclaw/.env` first, then the environment). Account `1` uses `TG_SESSION_STRING`, accounts `2-4` use the suffixed variant.
- **Gemini key** is read from `GEMINI_API_KEY` in `~/.bashrc` (fallback path); export it in your shell or adapt the loader.
- Only text posts are exported; media posts are recorded with metadata but their media is not downloaded.
