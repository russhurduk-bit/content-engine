#!/usr/bin/env python3
"""
Style Analyzer — анализирует экспортированные посты и строит профиль стиля.
Использует Gemini для глубокого анализа паттернов.
"""

import asyncio
import json
import os
import re
import sys
import statistics
from collections import Counter
from datetime import datetime

import httpx

sys.path.insert(0, '/root')
from ai_helper import call_ai, call_ai_vision

STYLES_DIR = "/root/content-engine/styles"
EXPORTS_DIR = "/root/content-engine/exports"

# Gemini key
GEMINI_KEY = ""
try:
    bashrc = open(os.path.expanduser("~/.bashrc")).read()
    m = re.search(r'GEMINI_API_KEY[=\s]+"?([A-Za-z0-9_-]+)', bashrc)
    if m:
        GEMINI_KEY = m.group(1)
except Exception:
    pass


def basic_stats(posts):
    """Compute basic text statistics."""
    lengths = []
    word_counts = []
    sentence_counts = []
    emoji_counts = []
    hashtag_counts = []
    link_counts = []
    all_words = []
    line_counts = []

    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF]+",
        flags=re.UNICODE
    )

    for post in posts:
        text = post["text"]
        lengths.append(len(text))
        words = text.split()
        word_counts.append(len(words))
        all_words.extend([w.lower().strip('.,!?;:()[]"') for w in words if len(w) > 2])
        sentences = re.split(r'[.!?]+', text)
        sentence_counts.append(len([s for s in sentences if s.strip()]))
        emoji_counts.append(len(emoji_pattern.findall(text)))
        hashtag_counts.append(len(re.findall(r'#\w+', text)))
        link_counts.append(len(re.findall(r'https?://\S+', text)))
        line_counts.append(text.count('\n') + 1)

    # Most common words (excluding common Russian stop words)
    stop_words = {'это', 'что', 'как', 'для', 'при', 'или', 'все', 'вот', 'уже', 'так',
                  'тоже', 'его', 'они', 'она', 'мне', 'вам', 'вас', 'нас', 'ваш', 'наш',
                  'мой', 'быть', 'есть', 'был', 'были', 'будет', 'который', 'если', 'только',
                  'когда', 'чтобы', 'потому', 'может', 'можно', 'нужно', 'надо', 'очень',
                  'просто', 'более', 'между', 'через', 'после', 'перед', 'даже', 'этого',
                  'этот', 'того', 'тот', 'ещё', 'еще', 'где', 'кто', 'чем', 'них', 'ним',
                  'него', 'неё', 'свой', 'свои', 'своё', 'себя', 'себе', 'без', 'под', 'над',
                  'про', 'ведь', 'бы', 'же'}
    word_freq = Counter(w for w in all_words if w not in stop_words and len(w) > 3)

    return {
        "total_posts": len(posts),
        "avg_length": round(statistics.mean(lengths)),
        "median_length": round(statistics.median(lengths)),
        "avg_words": round(statistics.mean(word_counts)),
        "avg_sentences": round(statistics.mean(sentence_counts), 1),
        "avg_lines": round(statistics.mean(line_counts), 1),
        "avg_emojis": round(statistics.mean(emoji_counts), 1),
        "posts_with_hashtags": sum(1 for c in hashtag_counts if c > 0),
        "posts_with_links": sum(1 for c in link_counts if c > 0),
        "posts_with_emojis": sum(1 for c in emoji_counts if c > 0),
        "top_words": word_freq.most_common(30),
        "length_distribution": {
            "short_under_200": sum(1 for l in lengths if l < 200),
            "medium_200_500": sum(1 for l in lengths if 200 <= l < 500),
            "long_500_1000": sum(1 for l in lengths if 500 <= l < 1000),
            "very_long_1000plus": sum(1 for l in lengths if l >= 1000),
        },
        "top_posts": sorted(posts, key=lambda p: p.get("views", 0), reverse=True)[:5],
    }


def extract_patterns(posts):
    """Extract structural patterns from posts."""
    patterns = {
        "starts_with_emoji": 0,
        "starts_with_question": 0,
        "starts_with_bold": 0,
        "has_bullet_list": 0,
        "has_numbered_list": 0,
        "has_call_to_action": 0,
        "ends_with_question": 0,
        "ends_with_emoji": 0,
        "uses_bold": 0,
        "uses_italic": 0,
        "uses_code": 0,
        "has_separator_lines": 0,
    }

    emoji_start = re.compile(r'^[\U0001F000-\U0001FAFF]')
    cta_patterns = re.compile(r'подпис|ссылк|комментар|перейди|жми|нажми|регистрир|записывай|переходи|забирай|скачай', re.I)

    openings = []
    closings = []

    for post in posts:
        text = post["text"]
        lines = text.split('\n')
        first_line = lines[0].strip() if lines else ""
        last_line = lines[-1].strip() if lines else ""

        if emoji_start.match(first_line):
            patterns["starts_with_emoji"] += 1
        if first_line.endswith('?'):
            patterns["starts_with_question"] += 1
        if first_line.startswith('**') or first_line.startswith('__'):
            patterns["starts_with_bold"] += 1
        if any(re.match(r'^[\-•▪️●]\s', l) for l in lines):
            patterns["has_bullet_list"] += 1
        if any(re.match(r'^\d+[\.\)]\s', l) for l in lines):
            patterns["has_numbered_list"] += 1
        if cta_patterns.search(text):
            patterns["has_call_to_action"] += 1
        if last_line.endswith('?'):
            patterns["ends_with_question"] += 1
        if emoji_start.match(last_line[-1:] if last_line else ""):
            patterns["ends_with_emoji"] += 1
        if '**' in text:
            patterns["uses_bold"] += 1
        if re.search(r'(?<!\*)\*(?!\*)\w', text):
            patterns["uses_italic"] += 1
        if '`' in text:
            patterns["uses_code"] += 1
        if any(set(l.strip()) <= {'—', '-', '─', '━', '=', '~'} and len(l.strip()) > 3 for l in lines):
            patterns["has_separator_lines"] += 1

        # Collect openings and closings
        if first_line:
            openings.append(first_line[:100])
        if last_line and last_line != first_line:
            closings.append(last_line[:100])

    return {
        "structural_patterns": {k: round(v / len(posts) * 100) for k, v in patterns.items()},
        "sample_openings": openings[:10],
        "sample_closings": closings[:10],
    }


async def ai_deep_analysis(posts, basic, patterns, channel_title):
    """Use Gemini to do deep style analysis."""
    if not GEMINI_KEY:
        return "❌ No Gemini API key"

    # Sample posts for analysis (top + random)
    sample = []
    top = sorted(posts, key=lambda p: p.get("views", 0), reverse=True)[:10]
    sample.extend(top)
    # Add some regular posts
    step = max(1, len(posts) // 10)
    for i in range(0, len(posts), step):
        if posts[i] not in sample:
            sample.append(posts[i])
        if len(sample) >= 20:
            break

    posts_text = "\n\n---POST---\n\n".join(p["text"][:500] for p in sample)

    prompt = f"""Ты — эксперт по анализу контента и копирайтингу. Проанализируй стиль автора канала "{channel_title}" по его постам.

Статистика:
- Всего постов: {basic['total_posts']}
- Средняя длина: {basic['avg_words']} слов, {basic['avg_lines']} строк
- Эмодзи: {basic['avg_emojis']} на пост, используются в {basic['posts_with_emojis']}% постов
- Хештеги: в {basic['posts_with_hashtags']} постах
- Ссылки: в {basic['posts_with_links']} постах
- Структура: {json.dumps(patterns['structural_patterns'], ensure_ascii=False)}

Посты (выборка {len(sample)} из {len(posts)}):

{posts_text}

Напиши ПОДРОБНЫЙ анализ стиля автора. Структура:

1. **ГОЛОС И ТОНАЛЬНОСТЬ** — как автор общается с аудиторией, какие эмоции создаёт
2. **ЛЕКСИКА** — характерные слова, обороты, жаргон, слова-паразиты
3. **СТРУКТУРА ПОСТОВ** — как начинает, как заканчивает, форматирование
4. **ПРИЁМЫ ВОВЛЕЧЕНИЯ** — как цепляет внимание, CTA, вопросы
5. **ТЕМЫ И КОНТЕНТ** — основные темы, соотношение пользы/развлечения/продаж
6. **УНИКАЛЬНЫЕ ПАТТЕРНЫ** — что делает стиль узнаваемым, фишки автора
7. **ФОРМУЛА ПОСТА** — типичная структура от начала до конца
8. **СТОП-ЛИСТ** — что автор НИКОГДА не делает (важно для генерации)

Формат: markdown, 1500-2500 слов. Конкретика > абстракции. Примеры из постов."""

    # Primary: ai-helper
    try:
        text = await asyncio.to_thread(call_ai, prompt, 0.3, 8192)
        if text:
            return text
    except Exception:
        pass

    # Gemini fallback (dead-last)
    if not GEMINI_KEY:
        return "❌ No AI available"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 8192,
                    "thinkingConfig": {"thinkingBudget": 8000},
                },
            },
        )
        data = resp.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = ""
        for part in parts:
            if not part.get("thought") and part.get("text"):
                text = part["text"]
        return text


async def analyze(json_path, channel_name=None):
    """Full analysis pipeline."""
    print(f"📊 Loading: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    posts = data["posts"]
    title = channel_name or data.get("channel", {}).get("title", "Unknown")
    print(f"📝 Channel: {title}, posts: {len(posts)}")

    # Step 1: Basic stats
    print("📈 Computing stats...")
    basic = basic_stats(posts)

    # Step 2: Pattern extraction
    print("🔍 Extracting patterns...")
    pats = extract_patterns(posts)

    # Step 3: AI deep analysis
    print("🧠 AI deep analysis (Gemini)...")
    ai_analysis = await ai_deep_analysis(posts, basic, pats, title)
    print(f"✅ AI analysis: {len(ai_analysis)} chars")

    # Save style profile
    safe_name = re.sub(r'[^\w\s\-]', '', title).strip().replace(' ', '_')[:50]
    profile = {
        "channel": title,
        "analyzed_at": datetime.now().isoformat(),
        "basic_stats": basic,
        "patterns": pats,
    }

    # Remove non-serializable top_posts text truncation
    for p in profile["basic_stats"].get("top_posts", []):
        p["text"] = p["text"][:200] + "..." if len(p.get("text", "")) > 200 else p.get("text", "")

    # JSON profile
    profile_path = os.path.join(STYLES_DIR, f"{safe_name}_profile.json")
    with open(profile_path, 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"💾 Profile: {profile_path}")

    # Markdown style guide
    guide_path = os.path.join(STYLES_DIR, f"{safe_name}_style.md")
    top_words_str = ", ".join(f"{w} ({c})" for w, c in basic["top_words"][:15])

    guide = f"""# Стиль-гайд: {title}

*Анализ: {datetime.now().strftime('%Y-%m-%d')} | Постов: {basic['total_posts']}*

## Ключевые метрики
- Средняя длина: {basic['avg_words']} слов / {basic['avg_lines']} строк
- Эмодзи: {basic['avg_emojis']} на пост ({basic['posts_with_emojis']} постов с эмодзи)
- Хештеги: {basic['posts_with_hashtags']} постов
- Ссылки: {basic['posts_with_links']} постов
- Распределение: {basic['length_distribution']['short_under_200']} коротких / {basic['length_distribution']['medium_200_500']} средних / {basic['length_distribution']['long_500_1000']} длинных / {basic['length_distribution']['very_long_1000plus']} очень длинных

## Частые слова
{top_words_str}

## Структурные паттерны
"""
    for k, v in pats["structural_patterns"].items():
        guide += f"- {k}: {v}%\n"

    guide += f"""
## AI Анализ стиля

{ai_analysis}
"""

    with open(guide_path, 'w', encoding='utf-8') as f:
        f.write(guide)
    print(f"📖 Style guide: {guide_path}")

    return {"profile": profile_path, "guide": guide_path}


async def main():
    if len(sys.argv) < 2:
        print("Usage: style_analyzer.py <export.json> [channel_name]")
        print("Example: style_analyzer.py /root/content-engine/exports/my_channel.json")
        return

    json_path = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else None
    result = await analyze(json_path, name)
    print(f"\n🎉 Done: {result}")


if __name__ == "__main__":
    asyncio.run(main())
