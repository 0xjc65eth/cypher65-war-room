#!/usr/bin/env python3
"""
BITMINER33 COMMUNITY — Launcher v3
"""

from rich.console import Console
from rich.prompt import Prompt

console = Console()

def main():
    console.print("""
[bold green]BITMINER33 COMMUNITY — CYPHERPUNK RAFFLE v3[/bold green]

[1] Terminal Clássico (Rich)
[2] TUI Avançada (Textual)
[3] Telegram Bot
[4] YouTube Comments Raffle
[5] Interface Web (Flask)
""")

    choice = Prompt.ask("Escolha o modo", choices=["1","2","3","4","5"])

    if choice == "1":
        import bitminer33
        bitminer33.main_menu()
    elif choice == "2":
        from tui.tui_app import BitminerTUI
        BitminerTUI().run()
    elif choice == "3":
        from telegram.telegram_bot import bot
        bot.polling()
    elif choice == "4":
        from youtube.youtube_raffle import extract_youtube_comments
        url = Prompt.ask("URL do vídeo do YouTube")
        participantes = extract_youtube_comments(url)
        console.print(f"[green]Extraídos {len(participantes)} participantes válidos[/green]")
    elif choice == "5":
        from web.app import app
        console.print("[bold green]Iniciando interface web em http://localhost:5000[/bold green]")
        app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    main()