#!/usr/bin/env python3
"""
BITMINER33 — Interface Web Cypherpunk
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
import os
import sys
from datetime import datetime

# Adiciona o diretório raiz ao path para conseguir importar o core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fair_engine import generate_super_fair_seed, provably_fair_draw, save_audit, get_bitcoin_block_hash

app = Flask(__name__)
CURRENT_FILE = "../data/current_raffle.json"
AUDIT_DIR = "../audits"

def load_current():
    if os.path.exists(CURRENT_FILE):
        with open(CURRENT_FILE) as f:
            return json.load(f)
    return None

def save_current(raffle):
    os.makedirs("../data", exist_ok=True)
    with open(CURRENT_FILE, "w") as f:
        json.dump(raffle, f, indent=2)

@app.route("/")
def index():
    raffle = load_current()
    return render_template("index.html", raffle=raffle)

@app.route("/create", methods=["POST"])
def create_raffle():
    nome = request.form.get("nome", "Sorteio BITMINER33")
    qtd = int(request.form.get("ganhadores", 3))

    raffle = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "nome": nome,
        "ganhadores": qtd,
        "participantes": [],
        "external_seed": get_bitcoin_block_hash(),
        "criado_em": datetime.now().isoformat()
    }
    save_current(raffle)
    return redirect(url_for("index"))

@app.route("/join", methods=["POST"])
def join_raffle():
    raffle = load_current()
    if not raffle:
        return "Nenhum sorteio ativo", 400

    nome = request.form.get("nome", "Anon")
    raffle["participantes"].append({
        "id": len(raffle["participantes"]) + 1,
        "nome": nome,
        "data": datetime.now().isoformat()
    })
    save_current(raffle)
    return redirect(url_for("index"))

@app.route("/draw", methods=["POST"])
def draw():
    raffle = load_current()
    if not raffle:
        return "Nenhum sorteio ativo", 400

    if len(raffle["participantes"]) < raffle["ganhadores"]:
        return "Participantes insuficientes", 400

    seed, sources = generate_super_fair_seed(raffle["participantes"], raffle.get("external_seed"))
    winners = provably_fair_draw(raffle["participantes"], raffle["ganhadores"], seed)

    raffle["winners"] = winners
    raffle["final_seed"] = seed
    raffle["entropy_sources"] = sources
    raffle["sorteado_em"] = datetime.now().isoformat()

    audit_path = save_audit(raffle["id"], seed, sources, winners, raffle["participantes"])
    os.remove(CURRENT_FILE)

    return render_template("result.html", raffle=raffle, audit_path=audit_path)

@app.route("/audits")
def audits():
    audits_list = []
    if os.path.exists(AUDIT_DIR):
        for f in sorted(os.listdir(AUDIT_DIR), reverse=True)[:10]:
            audits_list.append(f)
    return render_template("audits.html", audits=audits_list)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)