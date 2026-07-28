#!/usr/bin/env python3
"""
BITMINER33 COMMUNITY — Telegram Bot v2 (Cypherpunk)
Comandos expandidos + suporte a YouTube + auditoria
"""

import telebot
import json
import os
from datetime import datetime
from core.fair_engine import generate_fair_seed, provably_fair_draw, save_audit, get_bitcoin_block_hash
from youtube.youtube_raffle import extract_youtube_comments

TOKEN = "SEU_TOKEN_AQUI"
ADMIN_IDS = [123456789]

bot = telebot.TeleBot(TOKEN)
CURRENT_FILE = "data/current_raffle.json"

def load_current():
    if os.path.exists(CURRENT_FILE):
        with open(CURRENT_FILE, "r") as f:
            return json.load(f)
    return None

def save_current(raffle):
    os.makedirs("data", exist_ok=True)
    with open(CURRENT_FILE, "w") as f:
        json.dump(raffle, f, indent=2)

def delete_current():
    if os.path.exists(CURRENT_FILE):
        os.remove(CURRENT_FILE)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, """
`[ BITMINER33 COMMUNITY ]`
Sorteios Provably Fair • Cypherpunk Terminal

Comandos:
/criar - Criar sorteio
/participar - Entrar no sorteio
/participantes - Ver quem está participando
/sortear - Realizar sorteio (admin)
/info - Ver sorteio atual
/youtube - Sorteio por comentários do YT (admin)
/auditar - Ver última auditoria
/cancelar - Cancelar sorteio atual (admin)
""", parse_mode="Markdown")

@bot.message_handler(commands=['criar'])
def criar(message):
    if message.from_user.id not in ADMIN_IDS:
        return bot.reply_to(message, "Acesso negado.")

    raffle = {
        "id": datetime.now().strftime("%Y%m%d%H%M"),
        "nome": "Sorteio BITMINER33",
        "descricao": "Sorteio da comunidade",
        "ganhadores": 3,
        "participantes": [],
        "external_seed": get_bitcoin_block_hash(),
        "criado_em": datetime.now().isoformat()
    }
    save_current(raffle)
    bot.reply_to(message, f"✓ Sorteio criado!\nSeed Bitcoin: `{raffle['external_seed'][:16]}...`", parse_mode="Markdown")

@bot.message_handler(commands=['participar'])
def participar(message):
    raffle = load_current()
    if not raffle:
        return bot.reply_to(message, "Nenhum sorteio ativo.")

    user = message.from_user
    pid = str(user.id)
    nome = user.first_name or user.username or "Anon"

    if any(str(p["id"]) == pid for p in raffle["participantes"]):
        return bot.reply_to(message, "Você já está participando.")

    raffle["participantes"].append({
        "id": pid,
        "nome": nome,
        "data": datetime.now().isoformat()
    })
    save_current(raffle)
    bot.reply_to(message, f"✓ Inscrito no sorteio `{raffle['nome']}`")

@bot.message_handler(commands=['participantes'])
def participantes(message):
    raffle = load_current()
    if not raffle:
        return bot.reply_to(message, "Nenhum sorteio ativo.")
    total = len(raffle["participantes"])
    bot.reply_to(message, f"Participantes: `{total}`", parse_mode="Markdown")

@bot.message_handler(commands=['info'])
def info(message):
    raffle = load_current()
    if not raffle:
        return bot.reply_to(message, "Nenhum sorteio ativo.")
    bot.reply_to(message, f"`{raffle['nome']}`\nParticipantes: {len(raffle['participantes'])}", parse_mode="Markdown")

@bot.message_handler(commands=['sortear'])
def sortear(message):
    if message.from_user.id not in ADMIN_IDS:
        return

    raffle = load_current()
    if not raffle or len(raffle["participantes"]) < raffle["ganhadores"]:
        return bot.reply_to(message, "Participantes insuficientes.")

    seed, ext = generate_fair_seed(raffle["participantes"], raffle.get("external_seed"))
    winners = provably_fair_draw(raffle["participantes"], raffle["ganhadores"], seed)

    raffle["winners"] = winners
    raffle["final_seed"] = seed
    raffle["sorteado_em"] = datetime.now().isoformat()

    audit_path = save_audit(raffle["id"], seed, ext, winners, raffle["participantes"])
    delete_current()

    texto = "🎉 *SORTEIO REALIZADO*\n\n"
    for i, w in enumerate(winners, 1):
        texto += f"{i}. `{w['nome']}` (proof: `{w['proof']}`)\n"

    texto += f"\nSeed: `{seed[:24]}...`\nAudit: `{audit_path}`"
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['youtube'])
def youtube_raffle(message):
    if message.from_user.id not in ADMIN_IDS:
        return bot.reply_to(message, "Apenas admin.")

    msg = bot.reply_to(message, "Envie o link do vídeo do YouTube:")
    bot.register_next_step_handler(msg, process_youtube)

def process_youtube(message):
    url = message.text.strip()
    bot.reply_to(message, "Extraindo comentários... (pode demorar)")

    try:
        participantes = extract_youtube_comments(url, max_comments=300, filter_bots=True)
        if not participantes:
            return bot.reply_to(message, "Nenhum comentário válido encontrado.")

        raffle = {
            "id": datetime.now().strftime("%Y%m%d%H%M"),
            "nome": f"Sorteio YouTube - {url[-11:]}",
            "ganhadores": 3,
            "participantes": participantes,
            "external_seed": get_bitcoin_block_hash(),
            "criado_em": datetime.now().isoformat(),
            "fonte": "youtube"
        }
        save_current(raffle)
        bot.reply_to(message, f"✓ Sorteio criado com {len(participantes)} participantes válidos!")
    except Exception as e:
        bot.reply_to(message, f"Erro: {e}")

@bot.message_handler(commands=['auditar'])
def auditar(message):
    audits = sorted(os.listdir("audits")) if os.path.exists("audits") else []
    if not audits:
        return bot.reply_to(message, "Nenhuma auditoria encontrada.")
    last = audits[-1]
    bot.reply_to(message, f"Última auditoria: `{last}`", parse_mode="Markdown")

@bot.message_handler(commands=['cancelar'])
def cancelar(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if load_current():
        delete_current()
        bot.reply_to(message, "Sorteio cancelado.")
    else:
        bot.reply_to(message, "Nenhum sorteio ativo.")

print("[BITMINER33] Telegram bot v2 iniciado")
bot.polling()