#!/usr/bin/env python3
"""
BITMINER33 — YouTube Raffle Module (Melhorado)
- Extração de comentários
- Filtro anti-bot
- Remoção de spam
- Suporte a likes (heurística)
"""

import json
import subprocess
import tempfile
import os
import re
from typing import List, Dict
from datetime import datetime
from collections import Counter

def is_likely_bot(comment: str, author: str) -> bool:
    """Heurística simples para detectar bots/spam"""
    text = comment.lower()

    # Padrões comuns de bots
    spam_patterns = [
        r"ganhe grátis", r"clique aqui", r"link na bio", r"whatsapp",
        r"curso grátis", r"dinheiro fácil", r"bitcoin grátis",
        r"http[s]?://", r"bit\.ly", r"tinyurl"
    ]

    for pattern in spam_patterns:
        if re.search(pattern, text):
            return True

    # Comentários muito curtos ou repetitivos
    if len(comment) < 5:
        return True

    # Muitos emojis (comum em spam)
    emoji_count = len(re.findall(r'[😀-🙏🌀-🗿🚀-🛿]', comment))
    if emoji_count > 4:
        return True

    return False


def extract_youtube_comments(video_url: str, max_comments: int = 500, filter_bots: bool = True) -> List[Dict]:
    """
    Extrai comentários do YouTube usando yt-dlp.
    Aplica filtros anti-bot e anti-spam.
    """
    participants = []
    seen_authors = set()
    author_comments = Counter()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "video")
            cmd = [
                "yt-dlp",
                "--write-comments",
                "--no-download",
                "--skip-download",
                "-o", output,
                "--extractor-args", "youtube:player_client=web",
                video_url
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)

            comments_file = output + ".info.json"
            if not os.path.exists(comments_file):
                return []

            with open(comments_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            comments = data.get("comments", [])

            for c in comments[:max_comments]:
                author = c.get("author", "Unknown")
                author_id = str(c.get("author_id", author))
                text = c.get("text", "").strip()
                like_count = c.get("like_count", 0)

                # Filtros
                if filter_bots and is_likely_bot(text, author):
                    continue

                if author_id in seen_authors:
                    continue  # Evita duplicatas

                # Heurística de "like" (comentários com muitos likes têm mais peso)
                weight = 1 + (like_count // 10)

                seen_authors.add(author_id)
                author_comments[author_id] += 1

                participants.append({
                    "id": author_id,
                    "nome": author,
                    "comentario": text[:100],
                    "likes": like_count,
                    "peso": weight,
                    "data": datetime.utcnow().isoformat()
                })

    except Exception as e:
        print(f"[ERRO YT] {e}")

    return participants


def extract_from_file(json_path: str) -> List[Dict]:
    """Carrega participantes de exportação manual"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("participants", data)