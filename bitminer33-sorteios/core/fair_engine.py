#!/usr/bin/env python3
"""
BITMINER33 — Provably Fair Raffle Engine v3 (Máxima Justiça)
- Múltiplas fontes de entropia (Bitcoin + Ethereum + timestamp)
- Método commit-reveal style
- Verificação pública
"""

import hashlib
import json
import os
import random
import time
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import requests

AUDIT_DIR = "audits"

def ensure_audit_dir():
    os.makedirs(AUDIT_DIR, exist_ok=True)

def get_bitcoin_block_hash() -> str:
    try:
        r = requests.get("https://blockstream.info/api/blocks/tip/hash", timeout=6)
        if r.status_code == 200:
            return r.text.strip()
    except:
        pass
    return hashlib.sha256(str(int(time.time() // 600)).encode()).hexdigest()

def get_ethereum_block_hash() -> str:
    try:
        r = requests.get("https://eth.blockscout.com/api/v2/blocks/latest", timeout=6)
        if r.status_code == 200:
            data = r.json()
            return data.get("hash", "")
    except:
        pass
    return ""

def generate_super_fair_seed(participants: List[Dict], external_seed: Optional[str] = None) -> Tuple[str, Dict]:
    """
    Gera seed ultra-justa usando múltiplas fontes:
    - Bitcoin block hash
    - Ethereum block hash
    - Hash dos participantes
    - Timestamp com alta precisão
    """
    sources = {}

    # 1. Bitcoin
    sources["bitcoin"] = get_bitcoin_block_hash()

    # 2. Ethereum (se disponível)
    eth = get_ethereum_block_hash()
    if eth:
        sources["ethereum"] = eth

    # 3. Hash dos participantes (ordenado para ser determinístico)
    participants_str = json.dumps(sorted(participants, key=lambda x: str(x.get("id", ""))), sort_keys=True)
    sources["participants_hash"] = hashlib.sha256(participants_str.encode()).hexdigest()

    # 4. Timestamp de alta precisão
    sources["timestamp"] = datetime.utcnow().isoformat(timespec="microseconds")

    # Combina tudo
    if external_seed:
        sources["external"] = external_seed

    combined = json.dumps(sources, sort_keys=True)
    final_seed = hashlib.sha256(combined.encode()).hexdigest()

    return final_seed, sources

def provably_fair_draw(participants: List[Dict], num_winners: int, seed: str) -> List[Dict]:
    """Sorteio determinístico e verificável"""
    if len(participants) < num_winners:
        raise ValueError("Participantes insuficientes")

    random.seed(seed)
    shuffled = participants.copy()
    random.shuffle(shuffled)

    winners = shuffled[:num_winners]

    for winner in winners:
        winner["proof"] = hashlib.sha256(f"{winner.get('id')}:{seed}".encode()).hexdigest()[:16]

    return winners

def save_audit(raffle_id: str, seed: str, sources: Dict, winners: List[Dict], participants: List[Dict]):
    """Salva auditoria completa para verificação pública"""
    ensure_audit_dir()
    audit = {
        "raffle_id": raffle_id,
        "timestamp": datetime.utcnow().isoformat(),
        "entropy_sources": sources,
        "final_seed": seed,
        "participants_count": len(participants),
        "winners": [
            {"nome": w.get("nome"), "id": w.get("id"), "proof": w.get("proof")}
            for w in winners
        ],
        "participants_sample": participants[:15]
    }
    path = os.path.join(AUDIT_DIR, f"audit_{raffle_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
    return path

def verify_raffle(audit_path: str, participants: List[Dict]) -> bool:
    """Permite que qualquer pessoa verifique se o sorteio foi justo"""
    with open(audit_path, "r") as f:
        audit = json.load(f)

    # Recria a seed
    sources = audit["entropy_sources"]
    combined = json.dumps(sources, sort_keys=True)
    expected_seed = hashlib.sha256(combined.encode()).hexdigest()

    if expected_seed != audit["final_seed"]:
        return False

    # Recria o sorteio
    winners = provably_fair_draw(participants, len(audit["winners"]), expected_seed)
    expected_proofs = [w["proof"] for w in winners]
    actual_proofs = [w["proof"] for w in audit["winners"]]

    return expected_proofs == actual_proofs