# BITMINER33 COMMUNITY — Cypherpunk Raffle System v3

Sistema **ultra justo** de sorteios com múltiplas fontes de entropia + interface web.

---

## 🔥 O que torna este sistema extremamente justo

- Usa **Bitcoin + Ethereum** block hashes como seed
- Combina com hash dos participantes
- Timestamp com microsegundos
- Todo sorteio é **100% verificável** publicamente
- Auditoria salva em `audits/`

---

## 🚀 Como Usar

### Interface Web (Recomendada)

```bash
cd web
python app.py
```

Acesse: `http://localhost:5000`

A interface web tem visual cypherpunk e permite:
- Criar sorteios
- Participar
- Realizar sorteio
- Ver auditorias

### Outros Modos

```bash
python main.py
```

Escolha entre:
- Terminal Clássico
- TUI Avançada
- Telegram Bot
- YouTube Raffle
- Interface Web

---

## ⚙️ Motor de Justiça (v3)

Localizado em `core/fair_engine.py`:

- `generate_super_fair_seed()` — Combina Bitcoin + Ethereum + Participantes
- `provably_fair_draw()` — Sorteio determinístico
- `verify_raffle()` — Permite verificação pública

---

**BITMINER33 COMMUNITY** — Não confie. Verifique.