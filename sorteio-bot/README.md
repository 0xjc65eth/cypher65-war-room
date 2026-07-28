# 🎉 Bot de Sorteios Online - Telegram

Bot completo para realizar sorteios no Telegram, ideal para Instagram, TikTok, YouTube e comunidades.

## ✨ Funcionalidades

- ✅ Criar sorteios com múltiplos ganhadores
- ✅ Participantes se inscrevem com um comando
- ✅ Sorteio aleatório justo
- ✅ Histórico de sorteios realizados
- ✅ Controle de administradores
- ✅ Interface em português

## 🚀 Como usar

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Configurar o bot

1. Abra o arquivo `bot.py`
2. Substitua `SEU_TOKEN_AQUI` pelo token do seu bot (pegue com @BotFather)
3. Coloque seu ID do Telegram em `ADMIN_IDS` (use @userinfobot para descobrir seu ID)

### 3. Executar o bot

```bash
python bot.py
```

## 📋 Comandos

| Comando | Descrição |
|---------|-----------|
| `/start` | Inicia o bot |
| `/criar` | Cria um novo sorteio (admin) |
| `/participar` | Entra no sorteio atual |
| `/participantes` | Lista os participantes |
| `/info` | Mostra informações do sorteio |
| `/sortear` | Realiza o sorteio (admin) |
| `/cancelar` | Cancela o sorteio atual (admin) |
| `/historico` | Mostra os últimos sorteios |

## 👑 Configuração de Administradores

No arquivo `bot.py`, edite a linha:

```python
ADMIN_IDS = [123456789]  # Coloque seu ID aqui
```

Você pode adicionar múltiplos IDs separados por vírgula.

## 📁 Arquivos gerados

- `sorteios.json` - Histórico de todos os sorteios
- `sorteio_atual.json` - Sorteio em andamento

## 💡 Dicas de uso

- Use em grupos ou canais do Telegram
- Perfeito para sorteios de seguidores do Instagram
- Os participantes podem se inscrever mesmo sem estar no grupo

---

**Desenvolvido por Julio Cesar**  
JC Hair Studio's 62 - 2026