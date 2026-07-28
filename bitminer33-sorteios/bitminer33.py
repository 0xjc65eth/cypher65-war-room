#!/usr/bin/env python3
"""
BITMINER33 COMMUNITY — Terminal Cypherpunk Raffle (v2)
Com efeitos visuais avançados + auditoria
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.live import Live
from rich import box
import time
import json
import os
from datetime import datetime

from core.fair_engine import (
    generate_fair_seed,
    provably_fair_draw,
    save_audit,
    get_bitcoin_block_hash
)

console = Console()
CURRENT_FILE = "data/current_raffle.json"

def print_banner():
    banner = """
[bold green]╔══════════════════════════════════════════════════════════════╗
║  ██████╗ ██╗████████╗███╗   ███╗██╗███╗   ██╗███████╗██████╗  ║
║  ██╔══██╗██║╚══██╔══╝████╗ ████║██║████╗  ██║██╔════╝██╔══██╗ ║
║  ██████╔╝██║   ██║   ██╔████╔██║██║██╔██╗ ██║█████╗  ██████╔╝ ║
║  ██╔══██╗██║   ██║   ██║╚██╔╝██║██║██║╚██╗██║██╔══╝  ██╔══██╗ ║
║  ██████╔╝██║   ██║   ██║ ╚═╝ ██║██║██║ ╚████║███████╗██║  ██║ ║
║  ╚═════╝ ╚═╝   ╚═╝   ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ║
║           BITMINER33 COMMUNITY — CYPHERPUNK RAFFLE v2        ║
╚══════════════════════════════════════════════════════════════╝[/bold green]
"""
    console.print(banner)

def matrix_effect(text, times=4):
    for _ in range(times):
        console.print(f"[dim green]{text}[/dim green]", end="\r")
        time.sleep(0.08)
    console.print(f"[bold green]{text}[/bold green]")

def load_current():
    if os.path.exists(CURRENT_FILE):
        with open(CURRENT_FILE) as f:
            return json.load(f)
    return None

def save_current(raffle):
    os.makedirs("data", exist_ok=True)
    with open(CURRENT_FILE, "w") as f:
        json.dump(raffle, f, indent=2)

def delete_current():
    if os.path.exists(CURRENT_FILE):
        os.remove(CURRENT_FILE)

def main_menu():
    print_banner()
    while True:
        console.print("\n[bold cyan]>>> MENU PRINCIPAL <<<[/bold cyan]")
        console.print("[green]1[/green] Criar sorteio (com seed Bitcoin)")
        console.print("[green]2[/green] Participar")
        console.print("[green]3[/green] Ver sorteio atual")
        console.print("[green]4[/green] Listar participantes")
        console.print("[green]5[/green] Realizar sorteio [red](ADMIN)[/red]")
        console.print("[green]6[/green] Histórico + Auditoria")
        console.print("[green]7[/green] Cancelar sorteio")
        console.print("[green]0[/green] Sair")

        choice = Prompt.ask("[bold green]ESCOLHA[/bold green]", choices=["0","1","2","3","4","5","6","7"])

        if choice == "1":
            criar_sorteio()
        elif choice == "2":
            participar()
        elif choice == "3":
            mostrar_atual()
        elif choice == "4":
            listar_participantes()
        elif choice == "5":
            realizar_sorteio()
        elif choice == "6":
            mostrar_historico()
        elif choice == "7":
            cancelar()
        elif choice == "0":
            break

def criar_sorteio():
    if load_current():
        console.print("[red]Já existe sorteio ativo![/red]")
        return

    nome = Prompt.ask("[green]Nome do sorteio[/green]")
    qtd = int(Prompt.ask("[green]Quantos ganhadores?[/green]"))

    with console.status("[green]Buscando hash do bloco Bitcoin..."):
        btc_seed = get_bitcoin_block_hash()

    raffle = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "nome": nome,
        "ganhadores": qtd,
        "participantes": [],
        "external_seed": btc_seed,
        "criado_em": datetime.now().isoformat()
    }
    save_current(raffle)
    console.print(Panel(f"[green]Seed Bitcoin:[/green] {btc_seed[:32]}...", title="SORTEIO CRIADO"))

def participar():
    raffle = load_current()
    if not raffle:
        console.print("[red]Nenhum sorteio ativo.[/red]")
        return
    nome = Prompt.ask("[green]Seu nome/handle[/green]")
    raffle["participantes"].append({
        "id": len(raffle["participantes"]) + 1,
        "nome": nome,
        "data": datetime.now().isoformat()
    })
    save_current(raffle)
    console.print("[bold green]✓ Inscrito com sucesso[/bold green]")

def mostrar_atual():
    raffle = load_current()
    if not raffle:
        console.print("[yellow]Nenhum sorteio.[/yellow]")
        return
    console.print(Panel(f"[bold]{raffle['nome']}[/bold]\nParticipantes: {len(raffle['participantes'])}", title="SORTEIO ATUAL"))

def listar_participantes():
    raffle = load_current()
    if not raffle:
        return
    table = Table(title="PARTICIPANTES")
    table.add_column("#")
    table.add_column("Nome")
    for i, p in enumerate(raffle["participantes"], 1):
        table.add_row(str(i), p["nome"])
    console.print(table)

def realizar_sorteio():
    raffle = load_current()
    if not raffle:
        return
    if len(raffle["participantes"]) < raffle["ganhadores"]:
        console.print("[red]Participantes insuficientes[/red]")
        return

    matrix_effect(">>> INICIANDO SORTEIO VERIFICÁVEL <<<")
    seed, ext = generate_fair_seed(raffle["participantes"], raffle["external_seed"])
    winners = provably_fair_draw(raffle["participantes"], raffle["ganhadores"], seed)

    raffle["winners"] = winners
    raffle["final_seed"] = seed
    raffle["sorteado_em"] = datetime.now().isoformat()

    audit_path = save_audit(raffle["id"], seed, ext, winners, raffle["participantes"])
    delete_current()

    console.print(Panel(f"[green]SEED FINAL:[/green]\n{seed}\n\n[cyan]AUDITORIA:[/cyan] {audit_path}", title="RESULTADO"))

def mostrar_historico():
    audits = sorted(os.listdir("audits")) if os.path.exists("audits") else []
    if not audits:
        console.print("[yellow]Nenhum sorteio auditado ainda.[/yellow]")
        return
    console.print("[bold green]Últimas auditorias:[/bold green]")
    for a in audits[-5:]:
        console.print(f"  - {a}")

def cancelar():
    if load_current() and Confirm.ask("[red]Cancelar sorteio?[/red]"):
        delete_current()
        console.print("[yellow]Cancelado.[/yellow]")

if __name__ == "__main__":
    main_menu()