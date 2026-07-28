#!/usr/bin/env python3
"""
BITMINER33 — TUI Avançada com Textual (v2)
Com abas, logs e explicação de uso
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Button, Static, DataTable, Input, Log, TabbedContent, TabPane
from textual.reactive import reactive
from textual import events
import json
import os
from datetime import datetime
from core.fair_engine import generate_fair_seed, provably_fair_draw, save_audit, get_bitcoin_block_hash

CURRENT_FILE = "../data/current_raffle.json"

class BitminerTUI(App):
    CSS = """
    Screen { background: #0a0a0a; color: #00ff9f; }
    Header { background: #001100; color: #00ff9f; }
    Button { background: #001a00; color: #00ff9f; border: tall #003300; }
    Button:hover { background: #003300; }
    DataTable { background: #0a0a0a; color: #00ff9f; }
    Log { background: #001100; color: #00ff9f; }
    """

    def compose(self) -> ComposeResult:
        yield Header("BITMINER33 COMMUNITY — CYPHERPUNK RAFFLE v2")
        
        with TabbedContent():
            with TabPane("SORTEIO", id="sorteio"):
                yield Container(
                    Horizontal(
                        Button("Criar Sorteio", id="criar", variant="success"),
                        Button("Participar", id="participar"),
                        Button("Sortear", id="sortear", variant="error"),
                        Button("Auditar", id="auditar"),
                    ),
                    id="menu"
                )
                yield Static("Nenhum sorteio ativo", id="status")
                yield DataTable(id="participantes")

            with TabPane("COMO USAR", id="como_usar"):
                yield Static("""
[bold green]COMO USAR O BITMINER33[/bold green]

[cyan]1. Criar Sorteio[/cyan]
   - Clique em "Criar Sorteio"
   - O sistema busca automaticamente o hash do último bloco do Bitcoin
   - Isso garante que o sorteio seja verificável por qualquer pessoa

[cyan]2. Participar[/cyan]
   - Usuários podem se inscrever manualmente ou via Telegram

[cyan]3. Realizar Sorteio[/cyan]
   - Clique em "Sortear"
   - O sistema gera uma seed final combinando:
     • Hash dos participantes
     • Hash do bloco Bitcoin
     • Timestamp
   - Cada ganhador recebe um "proof hash" para verificação

[cyan]4. Auditoria[/cyan]
   - Todo sorteio é salvo em audits/
   - Qualquer pessoa pode reproduzir o sorteio com os mesmos dados

[cyan]5. YouTube[/cyan]
   - Use o comando /youtube no Telegram
   - O bot extrai comentários reais do vídeo
   - Aplica filtros anti-bot automaticamente

[yellow]Filosofia: Não confie. Verifique.[/yellow]
                """, id="instrucoes")

            with TabPane("LOG", id="log"):
                yield Log(id="log_view", auto_scroll=True)

        yield Footer()

    def on_mount(self):
        self.refresh_status()
        self.query_one("#log_view", Log).write_line("[green]Sistema iniciado[/green]")

    def refresh_status(self):
        raffle = self.load_current()
        status = self.query_one("#status", Static)
        table = self.query_one(DataTable)

        if not raffle:
            status.update("[bold red]NENHUM SORTEIO ATIVO[/bold red]")
            table.clear()
            return

        status.update(f"[bold green]{raffle['nome']}[/bold green] | Participantes: {len(raffle['participantes'])}")

        table.clear(columns=True)
        table.add_columns("ID", "Nome", "Data")
        for p in raffle.get("participantes", []):
            table.add_row(str(p["id"]), p["nome"], p["data"][:16])

    def load_current(self):
        if os.path.exists(CURRENT_FILE):
            with open(CURRENT_FILE) as f:
                return json.load(f)
        return None

    def on_button_pressed(self, event: Button.Pressed):
        log = self.query_one("#log_view", Log)

        if event.button.id == "criar":
            self.criar_sorteio()
            log.write_line("[green]Sorteio criado com seed Bitcoin[/green]")
        elif event.button.id == "participar":
            self.participar()
            log.write_line("[cyan]Novo participante adicionado[/cyan]")
        elif event.button.id == "sortear":
            self.sortear()
            log.write_line("[bold red]SORTEIO REALIZADO[/bold red]")
        elif event.button.id == "auditar":
            self.auditar()
            log.write_line("[yellow]Auditoria solicitada[/yellow]")

    def criar_sorteio(self):
        raffle = {
            "id": datetime.now().strftime("%Y%m%d%H%M"),
            "nome": "BITMINER33 SORTEIO",
            "ganhadores": 3,
            "participantes": [],
            "external_seed": get_bitcoin_block_hash(),
            "criado_em": datetime.now().isoformat()
        }
        os.makedirs("../data", exist_ok=True)
        with open(CURRENT_FILE, "w") as f:
            json.dump(raffle, f, indent=2)
        self.refresh_status()

    def participar(self):
        raffle = self.load_current()
        if not raffle:
            return
        raffle["participantes"].append({
            "id": len(raffle["participantes"]) + 1,
            "nome": f"User_{len(raffle['participantes'])}",
            "data": datetime.now().isoformat()
        })
        with open(CURRENT_FILE, "w") as f:
            json.dump(raffle, f, indent=2)
        self.refresh_status()

    def sortear(self):
        raffle = self.load_current()
        if not raffle:
            return
        seed, ext = generate_fair_seed(raffle["participantes"], raffle.get("external_seed"))
        winners = provably_fair_draw(raffle["participantes"], raffle["ganhadores"], seed)
        raffle["winners"] = winners
        raffle["final_seed"] = seed
        save_audit(raffle["id"], seed, ext, winners, raffle["participantes"])
        os.remove(CURRENT_FILE)
        self.refresh_status()
        self.bell()

    def auditar(self):
        audits = sorted(os.listdir("../audits")) if os.path.exists("../audits") else []
        if audits:
            self.query_one("#status").update(f"[cyan]Última auditoria: {audits[-1]}[/cyan]")

if __name__ == "__main__":
    BitminerTUI().run()