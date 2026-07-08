#!/usr/bin/env python3
"""
TG Export — экспорт постов из TG каналов/чатов в JSON + Markdown.
Использует Telethon (аккаунт 1 — Лёха).
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient
from telethon.sessions import StringSession

# --- Config ---
import os
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

EXPORTS_DIR = os.getenv("EXPORTS_DIR", "exports")
VAULT_DIR = os.getenv("VAULT_DIR", "vault")


def get_session(account=1):
    """Get TG session string for account."""
    env_file = "/root/claudeclaw/.env"
    key = f"TG_SESSION_STRING{'_' + str(account) if account > 1 else ''}"
    try:
        content = open(env_file).read()
        m = re.search(rf'{key}=([^\n]+)', content)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return os.environ.get(key, "")


def sanitize_filename(name):
    return re.sub(r'[^\w\s\-]', '', name).strip().replace(' ', '_')[:50]


async def export_channel(channel, limit=500, account=1, since_days=None):
    """
    Export posts from a TG channel/chat.

    Args:
        channel: username, invite link, or chat ID
        limit: max posts to fetch
        account: TG account number (1-4)
        since_days: only posts from last N days
    """
    session = get_session(account)
    if not session:
        print(f"❌ No session for account {account}")
        return None

    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.start()

    try:
        entity = await client.get_entity(channel)
        title = getattr(entity, 'title', None) or getattr(entity, 'first_name', 'unknown')
        username = getattr(entity, 'username', None) or str(entity.id)
        print(f"📥 Exporting: {title} (@{username})")

        min_date = None
        if since_days:
            min_date = datetime.now(timezone.utc) - timedelta(days=since_days)

        posts = []
        count = 0
        async for msg in client.iter_messages(entity, limit=limit, offset_date=None):
            if min_date and msg.date < min_date:
                break

            text = msg.text or msg.message or ""
            if not text.strip():
                continue

            post = {
                "id": msg.id,
                "date": msg.date.isoformat(),
                "text": text,
                "views": getattr(msg, 'views', 0) or 0,
                "forwards": getattr(msg, 'forwards', 0) or 0,
                "replies": msg.replies.replies if msg.replies else 0,
                "has_media": bool(msg.media),
                "media_type": type(msg.media).__name__ if msg.media else None,
            }
            posts.append(post)
            count += 1
            if count % 100 == 0:
                print(f"  ... {count} posts")

        posts.reverse()  # chronological order
        print(f"✅ Exported {len(posts)} posts from {title}")

        # Save JSON
        safe_name = sanitize_filename(title)
        json_path = os.path.join(EXPORTS_DIR, f"{safe_name}.json")
        export_data = {
            "channel": {
                "title": title,
                "username": username,
                "id": entity.id,
            },
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_posts": len(posts),
            "posts": posts,
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        print(f"💾 JSON: {json_path}")

        # Convert to Markdown vault
        md_dir = os.path.join(VAULT_DIR, safe_name)
        os.makedirs(md_dir, exist_ok=True)

        # Index file
        index_lines = [f"# {title}\n", f"Экспорт: {len(posts)} постов\n\n"]

        for post in posts:
            date = datetime.fromisoformat(post["date"]).strftime("%Y-%m-%d")
            slug = f"{date}_{post['id']}"

            # Extract first line as title
            first_line = post["text"].split('\n')[0][:80].strip()
            if not first_line:
                first_line = f"Post {post['id']}"
            # Clean markdown-unfriendly chars from title
            clean_title = re.sub(r'[#\[\]|]', '', first_line).strip()

            md_content = f"""---
date: {date}
id: {post['id']}
views: {post['views']}
forwards: {post['forwards']}
replies: {post['replies']}
has_media: {post['has_media']}
tags: []
---

{post['text']}
"""
            md_path = os.path.join(md_dir, f"{slug}.md")
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)

            index_lines.append(f"- [[{slug}]] — {clean_title}\n")

        # Write index
        with open(os.path.join(md_dir, "_index.md"), 'w', encoding='utf-8') as f:
            f.writelines(index_lines)

        print(f"📁 Vault: {md_dir}/ ({len(posts)} files)")
        return {"json": json_path, "vault": md_dir, "count": len(posts)}

    finally:
        await client.disconnect()


async def main():
    if len(sys.argv) < 2:
        print("Usage: tg_export.py <channel_username_or_id> [limit] [account] [since_days]")
        print("Example: tg_export.py @durov 200 1 30")
        return

    channel = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    account = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    since_days = int(sys.argv[4]) if len(sys.argv) > 4 else None

    result = await export_channel(channel, limit, account, since_days)
    if result:
        print(f"\n🎉 Done: {result['count']} posts → {result['json']}")


if __name__ == "__main__":
    asyncio.run(main())
