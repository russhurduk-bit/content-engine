#!/usr/bin/env python3
"""
Content Generator — генерация контента в стиле автора.
Использует style profile + reference posts + Gemini.
"""

import asyncio
import json
import os
import re
import sys
import random
from datetime import datetime

import httpx

sys.path.insert(0, '/root')
from ai_helper import call_ai, call_ai_vision

STYLES_DIR = "/root/content-engine/styles"
EXPORTS_DIR = "/root/content-engine/exports"

GEMINI_KEY = ""
try:
    bashrc = open(os.path.expanduser("~/.bashrc")).read()
    m = re.search(r'GEMINI_API_KEY[=\s]+"?([A-Za-z0-9_-]+)', bashrc)
    if m:
        GEMINI_KEY = m.group(1)
except Exception:
    pass


def load_style(channel_name):
    """Load style profile and guide for a channel."""
    safe = re.sub(r'[^\w\s\-]', '', channel_name).strip().replace(' ', '_')[:50]

    profile_path = os.path.join(STYLES_DIR, f"{safe}_profile.json")
    guide_path = os.path.join(STYLES_DIR, f"{safe}_style.md")

    profile = None
    guide = ""

    if os.path.exists(profile_path):
        with open(profile_path) as f:
            profile = json.load(f)

    if os.path.exists(guide_path):
        with open(guide_path) as f:
            guide = f.read()

    return profile, guide


def get_reference_posts(channel_name, count=5, strategy="mixed"):
    """Get reference posts for context."""
    safe = re.sub(r'[^\w\s\-]', '', channel_name).strip().replace(' ', '_')[:50]
    json_path = os.path.join(EXPORTS_DIR, f"{safe}.json")

    if not os.path.exists(json_path):
        return []

    with open(json_path) as f:
        data = json.load(f)

    posts = data["posts"]
    if not posts:
        return []

    if strategy == "top":
        # Best performing posts
        return sorted(posts, key=lambda p: p.get("views", 0), reverse=True)[:count]
    elif strategy == "recent":
        return posts[-count:]
    else:
        # Mixed: some top, some random
        top = sorted(posts, key=lambda p: p.get("views", 0), reverse=True)[:count // 2 + 1]
        rest = [p for p in posts if p not in top]
        sample = random.sample(rest, min(count - len(top), len(rest)))
        return top + sample


async def generate(channel_name, topic, post_type="informational", count=1, tone=None, extra_instructions=None):
    """
    Generate content in the style of a channel.

    Args:
        channel_name: channel to mimic
        topic: what to write about
        post_type: informational, story, sales, opinion, list, tutorial
        count: how many variants
        tone: override tone (optional)
        extra_instructions: additional instructions
    """
    if not GEMINI_KEY:
        return {"error": "No Gemini API key"}

    profile, guide = load_style(channel_name)
    refs = get_reference_posts(channel_name, count=5)

    if not guide:
        return {"error": f"No style guide found for '{channel_name}'. Run style_analyzer.py first."}

    # Build reference section
    ref_text = ""
    if refs:
        ref_text = "## Примеры постов автора (для имитации стиля):\n\n"
        for i, p in enumerate(refs):
            ref_text += f"---ПРИМЕР {i+1} (views: {p.get('views', '?')})---\n{p['text'][:600]}\n\n"

    # Stats section
    stats = ""
    if profile:
        s = profile.get("basic_stats", {})
        stats = f"""
Средняя длина: {s.get('avg_words', '?')} слов, {s.get('avg_lines', '?')} строк
Эмодзи на пост: {s.get('avg_emojis', '?')}
"""

    type_hints = {
        "informational": "Информационный/полезный пост. Даёт ценность, учит, объясняет.",
        "story": "Сторителлинг. Личная история, кейс, опыт.",
        "sales": "Продающий пост. Описание оффера, CTA, ссылки.",
        "opinion": "Мнение/позиция. Автор делится своим взглядом.",
        "list": "Список/подборка. Топ-N, чек-лист, полезные ресурсы.",
        "tutorial": "Пошаговая инструкция. Как сделать X.",
    }

    variants_instruction = f"Напиши {count} РАЗНЫХ вариантов поста." if count > 1 else "Напиши ОДИН пост."
    tone_instruction = f"\nТональность: {tone}" if tone else ""

    prompt = f"""Ты — копирайтер-имитатор. Твоя задача — написать пост для Telegram-канала ТОЧНО в стиле автора.

## Стиль-гайд автора:
{guide[:4000]}

{ref_text}

## Метрики стиля:
{stats}

## Задание:
Тема: {topic}
Тип поста: {type_hints.get(post_type, post_type)}{tone_instruction}
{f"Дополнительно: {extra_instructions}" if extra_instructions else ""}

## Правила:
1. ИМИТИРУЙ стиль автора максимально точно — его лексику, обороты, структуру, эмодзи
2. НЕ ДОБАВЛЯЙ то, чего автор никогда не делает (см. стоп-лист в стиль-гайде)
3. Длина поста — соответствует средней длине постов автора ({profile.get('basic_stats', {}).get('avg_words', 100)} слов)
4. Эмодзи — ровно столько, сколько использует автор
5. Если автор использует хештеги — добавь. Если нет — не добавляй
6. Пост должен быть готов к публикации БЕЗ ПРАВОК
7. Пиши ТОЛЬКО пост, без комментариев типа "Вот пост:" или "Вариант 1:"

{variants_instruction}
{"Раздели варианты строкой ===ВАРИАНТ===" if count > 1 else ""}"""

    # Primary: ai-helper
    text = ""
    try:
        text = await asyncio.to_thread(call_ai, prompt, 0.7, 8192)
    except Exception as e:
        pass

    # Gemini fallback (dead-last)
    if not text and GEMINI_KEY:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0.7,
                            "maxOutputTokens": 8192,
                            "thinkingConfig": {"thinkingBudget": 10000},
                        },
                    },
                )
                data = resp.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                for part in parts:
                    if not part.get("thought") and part.get("text"):
                        text = part["text"]
        except Exception:
            pass

    if not text:
        return {"error": "Empty AI response"}

    # Split variants
    if count > 1:
        variants = [v.strip() for v in re.split(r'===\s*ВАРИАНТ\s*===', text) if v.strip()]
    else:
        variants = [text.strip()]

    return {
        "channel": channel_name,
        "topic": topic,
        "type": post_type,
        "variants": variants,
        "count": len(variants),
        "generated_at": datetime.now().isoformat(),
    }


async def main():
    if len(sys.argv) < 3:
        print("Usage: content_generator.py <channel_name> <topic> [type] [count]")
        print("Types: informational, story, sales, opinion, list, tutorial")
        print("Example: content_generator.py 'My Channel' 'Как выбрать ноутбук' list 3")
        return

    channel = sys.argv[1]
    topic = sys.argv[2]
    ptype = sys.argv[3] if len(sys.argv) > 3 else "informational"
    count = int(sys.argv[4]) if len(sys.argv) > 4 else 1

    result = await generate(channel, topic, ptype, count)

    if result.get("error"):
        print(f"❌ {result['error']}")
        return

    for i, v in enumerate(result["variants"]):
        print(f"\n{'='*50}")
        if len(result["variants"]) > 1:
            print(f"ВАРИАНТ {i+1}")
            print('='*50)
        print(v)

    print(f"\n✅ Generated {result['count']} variant(s)")


if __name__ == "__main__":
    asyncio.run(main())
