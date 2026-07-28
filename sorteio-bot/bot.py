#!/usr/bin/env python3
"""
Bot de Sorteios Online - Telegram
Desenvolvido por Julio Cesar | JC Hair Studio's 62
"""

import telebot
import json
import random
import os
from datetime import datetime
from typing import Dict, List, Optional

# ==================== CONFIGURAÇÕES ====================
TOKEN = "SEU_TOKEN_AQUI"  # Coloque seu token do @BotFather aqui
ADMIN_IDS = [123456789]  # Coloque seu ID do Telegram aqui (use @userinfobot)

# ==================== ARQUIVOS DE DADOS ====================
DATA_FILE = "sorteios.json"
CURRENT_RAFFLE_FILE = "sorteio_atual.json"

# ==================== FUNÇÕES DE DADOS ====================
def load_data() -> Dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"sorteios": []}

def save_data(data: Dict):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_current_raffle() -> Optional[Dict]:
    if os.path.exists(CURRENT_RAFFLE_FILE):
        with open(CURRENT_RAFFLE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_current_raffle(raffle: Dict):
    with open(CURRENT_RAFFLE_FILE, 'w', encoding='utf-8') as f:
        json.dump(raffle, f, ensure_ascii=False, indent=2)

def delete_current_raffle():
    if os.path.exists(CURRENT_RAFFLE_FILE):
        os.remove(CURRENT_RAFFLE_FILE)

# ==================== BOT ====================
bot = telebot.TeleBot(TOKEN)

# ==================== HANDLERS ====================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    nome = message.from_user.first_name
    texto = f"""
🎉 *Bem-vindo ao Bot de Sorteios Online!*

Olá, {nome}! Eu sou seu assistente de sorteios.

*Comandos disponíveis:*

/criar - Criar um novo sorteio
/participar - Participar do sorteio atual
/participantes - Ver quem está participando
/sortear - Realizar o sorteio (apenas admin)
/cancelar - Cancelar sorteio atual
/historico - Ver sorteios anteriores
/info - Informações do sorteio atual

Feito com ❤️ por *JC Hair Studio's 62*
"""
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['criar'])
def cmd_criar(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Apenas administradores podem criar sorteios.")
        return

    current = load_current_raffle()
    if current:
        bot.reply_to(message, "⚠️ Já existe um sorteio em andamento. Use /cancelar para encerrar o atual.")
        return

    msg = bot.reply_to(message, "📝 *Nome do sorteio:*\nEx: Sorteio iPhone 15 Pro", parse_mode="Markdown")
    bot.register_next_step_handler(msg, criar_nome)

def criar_nome(message):
    nome = message.text.strip()
    msg = bot.reply_to(message, "🏆 *Quantos ganhadores?*\nEx: 3", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: criar_ganhadores(m, nome))

def criar_ganhadores(message, nome):
    try:
        qtd = int(message.text.strip())
        if qtd < 1:
            raise ValueError
    except:
        msg = bot.reply_to(message, "❌ Digite um número válido de ganhadores.")
        bot.register_next_step_handler(msg, lambda m: criar_ganhadores(m, nome))
        return

    msg = bot.reply_to(message, "📝 *Descrição do sorteio:*\nEx: Sorteio para clientes da JC Hair Studio", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: criar_descricao(m, nome, qtd))

def criar_descricao(message, nome, qtd):
    descricao = message.text.strip()
    
    raffle = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "nome": nome,
        "descricao": descricao,
        "ganhadores": qtd,
        "participantes": [],
        "criado_em": datetime.now().isoformat(),
        "criado_por": message.from_user.first_name
    }
    
    save_current_raffle(raffle)
    
    texto = f"""
✅ *Sorteio criado com sucesso!*

🎁 *{nome}*
📝 {descricao}
🏆 {qtd} ganhador(es)

Para participar, os usuários devem usar o comando:
/participar

Use /info para ver os detalhes.
"""
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['participar'])
def cmd_participar(message):
    raffle = load_current_raffle()
    if not raffle:
        bot.reply_to(message, "❌ Não há sorteio em andamento no momento.")
        return

    user = message.from_user
    user_id = user.id
    nome = user.first_name
    username = f"@{user.username}" if user.username else nome

    # Verifica se já está participando
    for p in raffle["participantes"]:
        if p["id"] == user_id:
            bot.reply_to(message, "⚠️ Você já está participando deste sorteio!")
            return

    participante = {
        "id": user_id,
        "nome": nome,
        "username": username,
        "data": datetime.now().isoformat()
    }
    
    raffle["participantes"].append(participante)
    save_current_raffle(raffle)
    
    bot.reply_to(message, f"✅ Parabéns, {nome}! Você foi inscrito no sorteio *{raffle['nome']}* 🎉", parse_mode="Markdown")

@bot.message_handler(commands=['participantes'])
def cmd_participantes(message):
    raffle = load_current_raffle()
    if not raffle:
        bot.reply_to(message, "❌ Não há sorteio em andamento.")
        return

    participantes = raffle["participantes"]
    if not participantes:
        bot.reply_to(message, "📭 Ainda não há participantes neste sorteio.")
        return

    texto = f"👥 *Participantes do sorteio: {raffle['nome']}* ({len(participantes)})\n\n"
    
    for i, p in enumerate(participantes, 1):
        texto += f"{i}. {p['nome']} ({p['username']})\n"
    
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['info'])
def cmd_info(message):
    raffle = load_current_raffle()
    if not raffle:
        bot.reply_to(message, "❌ Não há sorteio em andamento.")
        return

    texto = f"""
🎁 *{raffle['nome']}*

📝 {raffle['descricao']}
🏆 {raffle['ganhadores']} ganhador(es)
👥 {len(raffle['participantes'])} participante(s)
📅 Criado em: {raffle['criado_em'][:16].replace('T', ' ')}
"""
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['sortear'])
def cmd_sortear(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Apenas administradores podem realizar sorteios.")
        return

    raffle = load_current_raffle()
    if not raffle:
        bot.reply_to(message, "❌ Não há sorteio em andamento.")
        return

    participantes = raffle["participantes"]
    qtd = raffle["ganhadores"]

    if len(participantes) < qtd:
        bot.reply_to(message, f"❌ Não há participantes suficientes. Precisa de pelo menos {qtd}.")
        return

    # Sorteio
    ganhadores = random.sample(participantes, qtd)
    
    # Salva no histórico
    data = load_data()
    raffle["ganhadores_sorteados"] = [
        {"nome": g["nome"], "username": g["username"]} for g in ganhadores
    ]
    raffle["sorteado_em"] = datetime.now().isoformat()
    data["sorteios"].append(raffle)
    save_data(data)
    
    # Remove sorteio atual
    delete_current_raffle()
    
    # Mensagem de resultado
    texto = f"""
🎉 *SORTEIO REALIZADO!*

🎁 *{raffle['nome']}*

🏆 *Ganhadores:*
"""
    for i, g in enumerate(ganhadores, 1):
        texto += f"\n{i}. {g['nome']} ({g['username']})"
    
    texto += f"\n\nTotal de participantes: {len(participantes)}"
    
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['cancelar'])
def cmd_cancelar(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Apenas administradores podem cancelar sorteios.")
        return

    if not load_current_raffle():
        bot.reply_to(message, "❌ Não há sorteio em andamento.")
        return

    delete_current_raffle()
    bot.reply_to(message, "✅ Sorteio cancelado com sucesso.")

@bot.message_handler(commands=['historico'])
def cmd_historico(message):
    data = load_data()
    sorteios = data.get("sorteios", [])
    
    if not sorteios:
        bot.reply_to(message, "📭 Nenhum sorteio realizado ainda.")
        return

    texto = "📜 *Histórico de Sorteios*\n\n"
    
    for s in sorteios[-5:]:  # Últimos 5
        ganhadores = s.get("ganhadores_sorteados", [])
        texto += f"🎁 *{s['nome']}*\n"
        texto += f"🏆 Ganhadores: {', '.join([g['nome'] for g in ganhadores])}\n"
        texto += f"📅 {s['sorteado_em'][:10]}\n\n"
    
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    cmd_start(message)

print("🤖 Bot de Sorteios Online iniciado!")
bot.polling()