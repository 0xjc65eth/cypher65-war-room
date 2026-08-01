"""
CYPHER SOLO MINING ADVISOR — Interactive CLI
=============================================
A proper terminal REPL for solo mining calculations.

Usage:
    python3 -m agents.solo_mining_advisor.cli

Commands:
    network                          — Show live network difficulty + BTC price
    calc --hashrate <H> --duration <h> [--difficulty <D>] [--json]
                                     — Calculate block probability
    compare --budget <BTC> --duration <h> [--braiins <p>] [--mrr <p>] [--json]
                                     — Compare Braiins vs MRR rental options
    status [--json]                  — Full mining dashboard
    ask <free-text query>            — Natural language mining query
    help                             — Show this help
    clear                            — Clear the screen
    exit / quit                      — Exit the terminal

    Append  > filename  to redirect output to a file.
    Append  --json      to get parseable JSON output.
"""

import os
import math
import io
import json
import sys
import atexit
from pathlib import Path
from contextlib import redirect_stdout

# ── ANSI colors ───────────────────────────────────────────────────────────
class C:
    """Terminal color codes. Safer than raw escape sequences."""
    RST   = "\033[0m"
    BOLD  = "\033[1m"
    DIM   = "\033[2m"
    RED   = "\033[31m"
    GREEN = "\033[32m"
    AMBER = "\033[33m"
    BLUE  = "\033[34m"
    MAG   = "\033[35m"
    CYAN  = "\033[36m"
    WHITE = "\033[37m"
    MUTED = "\033[90m"

    @staticmethod
    def ok(text):
        return f"{C.GREEN}[OK]{C.RST} {text}"

    @staticmethod
    def warn(text):
        return f"{C.AMBER}[WARN]{C.RST} {text}"

    @staticmethod
    def err(text):
        return f"{C.RED}[ERROR]{C.RST} {text}"

    @staticmethod
    def hint(text):
        return f"{C.MUTED}[HINT]{C.RST} {text}"

    @staticmethod
    def header(text):
        return f"{C.CYAN}{C.BOLD}─── {text} ───{C.RST}"


# ── readline setup ────────────────────────────────────────────────────────

# Command → allowed flags mapping (for tab completion)
_COMPLETIONS = {
    # first-word completions (command names + aliases)
    "__commands__": [
        "network", "calc", "compare", "status", "ask", "query",
        "chat", "conversa", "conversar", "talk",
        "help", "clear", "cls", "exit", "quit",
    ],
    # per-command flags and value hints
    "network": [],
    "calc": ["--hashrate", "--duration", "--difficulty"],
    "compare": ["--budget", "--duration", "--braiins", "--mrr", "--objective"],
    "status": [],
    "ask": [],
    "query": [],
    "chat": [],
    "conversa": [],
    "conversar": [],
    "talk": [],
    "help": [],
    "clear": [],
    "cls": [],
    "exit": [],
    "quit": [],
    # flag-value completions
    "--objective": ["EV", "JACKPOT", "VARIANCE_MIN"],
}

try:
    import readline
    _HISTFILE = os.path.join(os.path.expanduser("~"), ".cypher_solo_mining_history")
    _HISTORY_MAX = 500

    def _make_completer():
        """Build a readline completer function with context-aware suggestions."""
        def completer(text, state):
            """
            Readline completer callback.
            Called repeatedly with state=0,1,2,... until it returns None.
            text = the current word being completed (prefix).
            """
            # Get the full line buffer and cursor position
            line = readline.get_line_buffer()
            tokens = line.lstrip().split()

            # Case 1: completing the first token → suggest command names
            # Also handles partial commands with trailing space (e.g. "net " → "network")
            if not tokens or len(tokens) == 1:
                if tokens and line.endswith(" ") and tokens[0] in _COMPLETIONS:
                    pass  # full command + space → let Case 3 offer flags
                else:
                    # When line ends with space, readline passes text="" for the new word.
                    # Use the first token as the filter prefix instead.
                    prefix = tokens[0] if (tokens and line.endswith(" ") and not text) else text
                    options = [c for c in _COMPLETIONS["__commands__"] if c.startswith(prefix)]
                    if state < len(options):
                        return options[state]
                    return None

            # We have at least one token — determine the command
            verb = tokens[0].lower() if tokens else ""

            # Case 2: completing a flag value (previous token was a flag with value options)
            # e.g. "--objective " → [EV, JACKPOT, VARIANCE_MIN]
            #       "--objective E" → [EV]
            if tokens:
                # Determine which token is the flag whose value we're completing
                if line.endswith(" "):
                    prev = tokens[-1]           # just-completed flag before cursor
                else:
                    prev = tokens[-2] if len(tokens) >= 2 else None  # flag before current word
                if prev and prev in _COMPLETIONS and prev.startswith("--"):
                    options = [v for v in _COMPLETIONS[prev] if v.startswith(text)]
                    if state < len(options):
                        return options[state]
                    return None

            # Case 3: completing a flag for the current command
            if verb in _COMPLETIONS:
                flags = _COMPLETIONS[verb]
                # Only suggest flags that aren't already in the line
                already_used = set(t for t in tokens if t.startswith("--"))
                available = [f for f in flags if f not in already_used and f.startswith(text)]
                if state < len(available):
                    return available[state]
                return None

            # Case 4: generic flag completion when command is unknown but text starts with --
            if text.startswith("--"):
                all_flags = ["--hashrate", "--duration", "--difficulty",
                            "--budget", "--braiins", "--mrr", "--objective"]
                options = [f for f in all_flags if f.startswith(text)]
                if state < len(options):
                    return options[state]
                return None

            return None
        return completer

    def _setup_readline():
        """Configure readline with history persistence and tab completion."""
        try:
            readline.read_history_file(_HISTFILE)
        except (FileNotFoundError, PermissionError):
            pass
        readline.set_history_length(_HISTORY_MAX)
        readline.set_completer(_make_completer())
        readline.parse_and_bind("tab: complete")
        # Also show all matches on double-tab (some readline builds use different binding)
        try:
            readline.parse_and_bind("set show-all-if-ambiguous on")
        except Exception:
            pass
        atexit.register(readline.write_history_file, _HISTFILE)
    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False
    def _setup_readline():
        pass


# ── Banner ─────────────────────────────────────────────────────────────────
BANNER = rf"""
{C.CYAN}  ▄████████  ▄█   ▄█▓██   ██▓ ██▓███  ▓█████  ██▀███
 ███    ███ ███  ███▒██  ██▒▓██░  ██▒▓█   ▀ ▓██ ▒ ██▒
 ███    █▀  ███▌ ███ ▒██ ██░▓██░ ██▓▒▒███   ▓██ ░▄█ ▒
███        ███▌ ███ ░ ▐██▓░▒██▄█▓▒ ▒▒▓█  ▄ ▒██▀▀█▄
▀███████████▐█•▌ ██▓ ░ ██▒▓░▒██▒ ░  ░░▒████▒░██▓ ▒██▒
         ████▌  ██▒  ██▒▒▒ ▒▓█░ ░  ░░░ ▒░ ░░ ▒▓ ░▒▓░
   ▄█    ████▌  ██░▓██ ░▒░ ░▒ ░      ░ ░  ░  ░▒ ░ ▒░
 ▄████████▀ ▀▀  ▀░ ░ ▒  ░  ░░          ░     ░░   ░
                 ░░                     ░  ░   ░
{C.RST}
{C.BOLD}  CYPHER // SOLO MINING ADVISOR v1.0{C.RST}
  Real-time mining probability & rental comparison engine

  Type {C.GREEN}chat{C.RST} to enter continuous conversation mode.
  Type {C.GREEN}help{C.RST} for commands, {C.GREEN}exit{C.RST} to quit.
"""

# Neutral prompt identity — the CLI is a generic tool, not a personal shell.
_CLI_USER = os.environ.get("USER") or os.environ.get("USERNAME") or "miner"
PROMPT = f"{C.GREEN}{_CLI_USER}@cypher{C.RST}:{C.BLUE}~/solo-mining{C.RST}$ "
CHAT_PROMPT = f"{C.CYAN}💬 {C.RST}"


# ═══════════════════════════════════════════════════════════════════════════
#  IMPORTS (lazy — imported when first used to avoid startup cost)
# ═══════════════════════════════════════════════════════════════════════════

_solo_mining = None
_execute_tool = None


def _get_execute_tool():
    global _execute_tool
    if _execute_tool is None:
        from agents.solo_mining_advisor import execute_tool
        _execute_tool = execute_tool
    return _execute_tool


def _get_solo_mining():
    global _solo_mining
    if _solo_mining is None:
        import solo_mining
        _solo_mining = solo_mining
    return _solo_mining


# ═══════════════════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

def cmd_help():
    """Print help text."""
    print()
    print(f"{C.AMBER}{C.BOLD}COMMANDS:{C.RST}")
    print(f"  {C.GREEN}status{C.RST} {C.MUTED}[--json]{C.RST}")
    print(f"       Show full mining dashboard: difficulty, BTC price, worker stats, 24h probability")
    print()
    print(f"  {C.GREEN}network{C.RST} {C.MUTED}[--json]{C.RST}")
    print(f"       Show live Bitcoin network difficulty + BTC price")
    print()
    print(f"  {C.GREEN}calc --hashrate <value> --duration <h>{C.RST} {C.MUTED}[--difficulty <d>] [--json]{C.RST}")
    print(f"       Calculate solo mining probability (auto-fetches live difficulty)")
    print(f"       Examples: calc --hashrate 225TH --duration 24h")
    print(f"                 calc --hashrate 1.5PH --duration 168h --difficulty 127T")
    print()
    print(f"  {C.GREEN}compare --budget <btc> --duration <h>{C.RST} {C.MUTED}[--braiins <p>] [--mrr <p>] [--json]{C.RST}")
    print(f"       Compare Braiins vs MRR rental options (auto-fetches live prices)")
    print(f"       Example: compare --budget 0.01 --duration 24h")
    print()
    print(f"  {C.GREEN}ask <free-text query>{C.RST}")
    print(f"       Natural language mining query")
    print(f"       Example: ask what is the current network difficulty?")
    print()
    print(f"  {C.GREEN}chat / conversa / conversar / talk{C.RST}")
    print(f"       Enter continuous conversation mode — every line is a")
    print(f"       natural language mining query. Type 'sair' to return.")
    print(f"       No 'ask' prefix needed: just type 'qual a chance com 500th?'")
    print()
    print(f"  {C.GREEN}Piping & JSON:{C.RST}")
    print(f"       Append {C.GREEN}> filename{C.RST} to save output to a file")
    print(f"       Append {C.GREEN}--json{C.RST} to get machine-parseable JSON output")
    print(f"       Examples: network > /tmp/stats.txt")
    print(f"                 calc --hashrate 225TH --duration 24h --json")
    print()
    print(f"  {C.GREEN}clear{C.RST}")
    print(f"       Clear the screen")
    print()
    print(f"  {C.GREEN}help{C.RST}")
    print(f"       Show this help text")
    print()
    print(f"  {C.GREEN}exit / quit{C.RST}")
    print(f"       Exit the terminal")
    print()


def cmd_clear():
    """Clear the terminal screen."""
    os.system("clear" if os.name == "posix" else "cls")


def cmd_status(json_mode=False):
    """Show a comprehensive mining dashboard in a single response.
    Fetches difficulty, BTC price, and parasite.space worker stats in parallel,
    then calculates 24h block probability using the worker's hashrate."""
    execute_tool = _get_execute_tool()
    sm = _get_solo_mining()

    if not json_mode:
        print()
        print(f"{C.MUTED}fetching live data from agent tools...{C.RST}")

    # Fetch all three data sources in sequence (tools.py doesn't support async)
    diff_result = execute_tool("get_network_difficulty")
    price_result = execute_tool("get_btc_price", {"currencies": "usd,brl"})
    pool_result = execute_tool("get_parasite_pool_stats")

    difficulty = diff_result.get("difficulty", 0)
    prices = price_result.get("prices", {})
    worker_hr = _coerce_float(pool_result.get("worker_hashrate", 0))
    pool_hr = _coerce_float(pool_result.get("pool_hashrate", 0))

    # Compute probability
    prob_data = None
    if worker_hr and difficulty:
        prob = sm.calc_block_probability(worker_hr, difficulty, 86400)
        exp_time = sm.calc_expected_time(worker_hr, difficulty)
        prob_data = {
            "p_at_least_1_block_pct": prob["p_at_least_1_block_pct"],
            "p_zero_blocks_pct": prob["p_zero_blocks_pct"],
            "expected_time_days": exp_time["days"],
            "expected_time_years": exp_time["years"],
            "hashes_24h": worker_hr * 86400,
            "lambda": prob["lambda"],
        }

    if json_mode:
        out = {
            "network": {
                "difficulty": difficulty,
                "difficulty_formatted": _fmt_diff_human(difficulty),
                "difficulty_source": diff_result.get("source"),
                "btc_prices": prices,
                "btc_source": price_result.get("source"),
            },
            "worker": {
                "hashrate": worker_hr,
                "hashrate_formatted": _fmt_hashrate_human(worker_hr),
                "best_share": pool_result.get("worker_best_diff"),
                "status": pool_result.get("worker_status"),
                "uptime_seconds": pool_result.get("worker_uptime"),
            },
            "pool": {
                "hashrate": pool_hr,
                "hashrate_formatted": _fmt_hashrate_human(pool_hr),
                "workers": pool_result.get("pool_workers"),
                "users": pool_result.get("pool_users"),
                "data_status": pool_result.get("pool_status"),
            },
            "probability_24h": prob_data,
        }
        return out

    print()
    print(C.ok("Live data fetched"))
    print()

    # ══ Header block ══
    print(f"{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════╗{C.RST}")
    print(f"{C.CYAN}{C.BOLD}║{C.RST}          {C.BOLD}CYPHER MINING STATUS{C.RST}              {C.CYAN}{C.BOLD}║{C.RST}")
    print(f"{C.CYAN}{C.BOLD}╚══════════════════════════════════════════════╝{C.RST}")
    print()

    # ── Network section ──
    print(C.header("Network"))
    if difficulty:
        print(f"  {C.BOLD}Difficulty{C.RST}        {C.WHITE}{difficulty:,.0f}{C.RST}  ({C.MUTED}{_fmt_diff_human(difficulty)}{C.RST})")
        print(f"  {C.BOLD}Source{C.RST}           {C.MUTED}{diff_result.get('source', 'agent')}{C.RST}")
    else:
        print(f"  {C.RED}Difficulty unavailable{C.RST}")

    print()
    if prices:
        parts = []
        if prices.get("usd"): parts.append(f"{C.WHITE}${prices['usd']:,.0f}{C.RST}")
        if prices.get("brl"): parts.append(f"{C.WHITE}R${prices['brl']:,.0f}{C.RST}")
        print(f"  {C.BOLD}BTC Price{C.RST}        {' / '.join(parts)}")
    print()

    # ── Worker section ──
    print(C.header("Worker"))
    if worker_hr:
        print(f"  {C.BOLD}Hashrate{C.RST}        {C.WHITE}{_fmt_hashrate_human(worker_hr)}{C.RST}")
    else:
        print(f"  {C.BOLD}Hashrate{C.RST}        {C.MUTED}no worker data from pool{C.RST}")

    best_diff_str = pool_result.get("worker_best_diff", "—")
    print(f"  {C.BOLD}Best Share{C.RST}      {C.WHITE}{best_diff_str}{C.RST}")

    worker_status = pool_result.get("worker_status", "unknown")
    status_color = C.GREEN if worker_status == "online" else C.RED
    print(f"  {C.BOLD}Status{C.RST}          {status_color}{worker_status.upper()}{C.RST}")

    uptime = pool_result.get("worker_uptime")
    if uptime:
        print(f"  {C.BOLD}Uptime{C.RST}          {C.WHITE}{_fmt_uptime_human(uptime)}{C.RST}")

    print()

    # ── Pool section ──
    print(C.header("Pool (parasite.space)"))
    if pool_hr:
        print(f"  {C.BOLD}Pool Hashrate{C.RST}   {C.WHITE}{_fmt_hashrate_human(pool_hr)}{C.RST}")
    print(f"  {C.BOLD}Workers{C.RST}         {C.WHITE}{pool_result.get('pool_workers', '—')}{C.RST} / {C.WHITE}{pool_result.get('pool_users', '—')} users{C.RST}")
    print(f"  {C.BOLD}Data Status{C.RST}     {C.MUTED}{pool_result.get('pool_status', 'unknown')}{C.RST}")
    print()

    # ── Probability section (24h default) ──
    if prob_data:
        print(C.header("24h Block Probability"))
        pct = prob_data["p_at_least_1_block_pct"]
        if pct < 0.0001:
            pct_str = f"{pct:.6f}%"
        elif pct < 0.01:
            pct_str = f"{pct:.4f}%"
        else:
            pct_str = f"{pct:.2f}%"

        print(f"  {C.BOLD}P(>=1 block){C.RST}     {C.WHITE}{pct_str}{C.RST}")
        print(f"  {C.BOLD}P(0 blocks){C.RST}      {C.MUTED}{prob_data['p_zero_blocks_pct']:.1f}%{C.RST}")
        print(f"  {C.BOLD}E[time]{C.RST}           {C.WHITE}{prob_data['expected_time_days']:,.0f} days{C.RST} {C.MUTED}({prob_data['expected_time_years']:.1f} years){C.RST}")
        print(f"  {C.BOLD}Hashes/24h{C.RST}      {C.WHITE}{prob_data['hashes_24h']:,.0f}{C.RST}")
        print()
        if pct < 0.01:
            print(C.warn("Extremely low probability — solo mining is a lottery."))
        print()
    else:
        if not worker_hr and not difficulty:
            print(C.warn("Block probability skipped — both hashrate and difficulty are missing."))
        elif not worker_hr:
            print(C.warn("Block probability skipped — no worker hashrate from parasite.space."))
        elif not difficulty:
            print(C.warn("Block probability skipped — network difficulty unavailable."))
        print()

    print(C.ok("Status complete."))
    print()


def cmd_network(json_mode=False):
    """Fetch and display live network difficulty + BTC price using agent tools."""
    execute_tool = _get_execute_tool()

    if not json_mode:
        print()
        print(f"{C.MUTED}fetching live data from agent tools...{C.RST}")

    # Fetch difficulty
    diff_result = execute_tool("get_network_difficulty")
    # Fetch BTC price
    price_result = execute_tool("get_btc_price", {"currencies": "usd,brl"})

    if json_mode:
        out = {
            "difficulty": diff_result.get("difficulty"),
            "difficulty_formatted": _fmt_diff_human(diff_result.get("difficulty", 0)),
            "difficulty_source": diff_result.get("source"),
            "btc_prices": price_result.get("prices", {}),
            "btc_source": price_result.get("source"),
        }
        if diff_result.get("error"):
            out["difficulty_error"] = diff_result["error"]
        if price_result.get("error"):
            out["btc_error"] = price_result["error"]
        return out

    print()
    print(C.ok("Agent tools executed"))
    print()
    print(C.header("Network Difficulty"))
    if diff_result.get("difficulty"):
        diff = diff_result["difficulty"]
        print(f"  {C.BOLD}difficulty{C.RST}........ {C.WHITE}{diff:,.0f}{C.RST}")
        print(f"  {C.BOLD}formatted{C.RST}......... {C.WHITE}{_fmt_diff_human(diff)}{C.RST}")
        print(f"  {C.BOLD}source{C.RST}............ {C.MUTED}{diff_result.get('source', 'agent tool')}{C.RST}")
    else:
        print(C.err(f"Difficulty: {diff_result.get('error', 'unavailable')}"))

    print()
    print(C.header("BTC Price"))
    prices = price_result.get("prices", {})
    if prices:
        if prices.get("usd"):
            print(f"  {C.BOLD}btc/usd{C.RST}........... {C.WHITE}${prices['usd']:,.0f}{C.RST}")
        if prices.get("brl"):
            print(f"  {C.BOLD}btc/brl{C.RST}........... {C.WHITE}R${prices['brl']:,.0f}{C.RST}")
        if prices.get("eur"):
            print(f"  {C.BOLD}btc/eur{C.RST}........... {C.WHITE}€{prices['eur']:,.0f}{C.RST}")
        print(f"  {C.BOLD}source{C.RST}............ {C.MUTED}{price_result.get('source', 'coingecko.com')}{C.RST}")
    else:
        print(C.err(f"BTC price: {price_result.get('error', 'unavailable')}"))

    print()


def cmd_calc(args, json_mode=False):
    """Parse calc command and run probability calculations."""
    sm = _get_solo_mining()
    execute_tool = _get_execute_tool()

    # Parse flags
    hashrate = None
    duration = None
    difficulty = None

    i = 0
    while i < len(args):
        if args[i] == "--hashrate" and i + 1 < len(args):
            hashrate = args[i + 1]
            i += 2
        elif args[i] == "--duration" and i + 1 < len(args):
            try:
                duration = float(args[i + 1].replace("h", "").replace("H", ""))
            except ValueError:
                print(C.err(f"Invalid duration: {args[i + 1]}"))
                return
            i += 2
        elif args[i] == "--difficulty" and i + 1 < len(args):
            difficulty = args[i + 1]
            i += 2
        else:
            i += 1

    if not hashrate or not duration:
        print(C.err("Missing required flags. Usage: calc --hashrate <value> --duration <h> [--difficulty <d>]"))
        print(C.hint("Example: calc --hashrate 225TH --duration 24h"))
        return

    # Auto-fetch difficulty if not provided
    if not difficulty:
        if not json_mode:
            print()
            print(f"{C.MUTED}fetching live difficulty from agent tools...{C.RST}")
        diff_result = execute_tool("get_network_difficulty")
        if diff_result.get("difficulty"):
            difficulty = diff_result["difficulty"]
            if not json_mode:
                print(C.ok(f"Using live difficulty: {_fmt_diff_human(difficulty)} ({diff_result.get('source', 'agent')})"))
        else:
            if not json_mode:
                print(C.warn("Could not fetch live difficulty — using default 127T"))
            difficulty = 127e12
    else:
        difficulty = _parse_diff_float(difficulty)

    hashrate_hs = sm._parse_hashrate(hashrate)
    duration_seconds = duration * 3600

    prob = sm.calc_block_probability(hashrate_hs, difficulty, duration_seconds)
    exp_time = sm.calc_expected_time(hashrate_hs, difficulty)
    best_diff = sm.calc_best_diff_expected(hashrate_hs, duration_seconds)

    if json_mode:
        return {
            "hashrate": hashrate,
            "hashrate_hs": hashrate_hs,
            "duration_hours": duration,
            "duration_seconds": duration_seconds,
            "difficulty": difficulty,
            "difficulty_formatted": _fmt_diff_human(difficulty),
            "probability": {
                "hashes_per_block": prob["hashes_per_block"],
                "block_rate_per_sec": prob["block_rate_per_sec"],
                "lambda": prob["lambda"],
                "p_at_least_1_block_pct": prob["p_at_least_1_block_pct"],
                "p_zero_blocks_pct": prob["p_zero_blocks_pct"],
            },
            "expected_time": {
                "seconds": exp_time["seconds"],
                "days": exp_time["days"],
                "years": exp_time["years"],
            },
            "best_diff_expected": {
                "total_hashes": best_diff["total_hashes"],
                "expected_best_diff": best_diff["expected_best_diff"],
            },
        }

    print()
    print(C.ok("Parameters received"))
    print(f"  {C.BOLD}hashrate{C.RST}........... {C.WHITE}{hashrate}{C.RST} ({hashrate_hs:,.0f} H/s)")
    print(f"  {C.BOLD}duration{C.RST}............ {C.WHITE}{duration}h ({duration / 24:.2f} days){C.RST}")
    print(f"  {C.BOLD}difficulty{C.RST}.......... {C.WHITE}{difficulty:,.0f}{C.RST} ({_fmt_diff_human(difficulty)})")

    print()
    print(C.header("Block Discovery"))
    print(f"  {C.BOLD}Hashes per block{C.RST}.... {C.WHITE}{prob['hashes_per_block']:,.0f}{C.RST}")
    print(f"  {C.BOLD}Block rate{C.RST}........... {C.MUTED}{prob['block_rate_per_sec']:.6e}{C.RST} blocks/s")
    print(f"  {C.BOLD}Lambda(t){C.RST}............ {C.MUTED}{prob['lambda']:.6e}{C.RST}")
    print(f"  {C.BOLD}P(>=1 block){C.RST}......... {C.WHITE}{prob['p_at_least_1_block_pct']:.6f}%{C.RST}")
    print(f"  {C.BOLD}P(0 blocks){C.RST}.......... {C.MUTED}{prob['p_zero_blocks_pct']:.2f}%{C.RST}")

    print()
    print(C.header("Expected Time"))
    print(f"  {C.BOLD}E[time to block]{C.RST}.... {C.WHITE}{exp_time['days']:,.1f} days{C.RST}")
    print(f"                    {C.MUTED}= {exp_time['years']:,.2f} years{C.RST}")

    print()
    print(C.header("Best Difficulty (Estimated)"))
    print(f"  {C.BOLD}Total hashes{C.RST}......... {C.WHITE}{best_diff['total_hashes']:,.0f}{C.RST}")
    print(f"  {C.BOLD}Expected best diff{C.RST}... {C.WHITE}{best_diff['expected_best_diff']:,.1f}{C.RST}")

    print()
    print(C.warn("Solo mining is a lottery. EV is negative vs pool mining."))
    print(C.ok("Calculation complete."))
    print()


def cmd_compare(args, json_mode=False):
    """Parse compare command and run rental comparison."""
    sm = _get_solo_mining()
    execute_tool = _get_execute_tool()

    budget = None
    duration = None
    braiins_price = None
    mrr_price = None
    objective = "EV"

    i = 0
    while i < len(args):
        if args[i] == "--budget" and i + 1 < len(args):
            try:
                budget = float(args[i + 1])
            except ValueError:
                print(C.err(f"Invalid budget: {args[i + 1]}"))
                return
            i += 2
        elif args[i] == "--duration" and i + 1 < len(args):
            try:
                duration = float(args[i + 1].replace("h", "").replace("H", ""))
            except ValueError:
                print(C.err(f"Invalid duration: {args[i + 1]}"))
                return
            i += 2
        elif args[i] == "--braiins" and i + 1 < len(args):
            try:
                braiins_price = float(args[i + 1])
            except ValueError:
                print(C.err(f"Invalid braiins price: {args[i + 1]}"))
                return
            i += 2
        elif args[i] == "--mrr" and i + 1 < len(args):
            try:
                mrr_price = float(args[i + 1])
            except ValueError:
                print(C.err(f"Invalid mrr price: {args[i + 1]}"))
                return
            i += 2
        elif args[i] == "--objective" and i + 1 < len(args):
            objective = args[i + 1].upper()
            i += 2
        else:
            i += 1

    if not budget or not duration:
        print(C.err("Missing required flags. Usage: compare --budget <btc> --duration <h> [--braiins <p>] [--mrr <p>]"))
        print(C.hint("Example: compare --budget 0.01 --duration 24h"))
        return

    # Auto-fetch prices if not provided
    if braiins_price is None or mrr_price is None:
        if not json_mode:
            print()
            print(f"{C.MUTED}fetching live rental prices from agent tools...{C.RST}")

    if braiins_price is None:
        result = execute_tool("get_braiins_orderbook")
        if result.get("price_btc_per_ph_day") is not None:
            braiins_price = result["price_btc_per_ph_day"]
            if not json_mode:
                print(C.ok(f"Braiins: {braiins_price:.8f} BTC/PH/day ({result.get('available_asks', '?')} asks)"))
        elif not json_mode:
            print(C.warn(f"Braiins unavailable: {result.get('error', 'no data')}"))

    if mrr_price is None:
        result = execute_tool("get_mrr_listings")
        if result.get("price_btc_per_ph_day") is not None:
            mrr_price = result["price_btc_per_ph_day"]
            if not json_mode:
                print(C.ok(f"MRR: {mrr_price:.8f} BTC/PH/day ({result.get('total_listings', '?')} listings)"))
        elif not json_mode:
            if result.get("needs_auth"):
                print(C.warn(f"MRR: {result.get('error', 'credentials required')}"))
            else:
                print(C.warn(f"MRR unavailable: {result.get('error', 'no data')}"))

    # Get difficulty
    diff_result = execute_tool("get_network_difficulty")
    difficulty = diff_result.get("difficulty", 127e12)
    if not diff_result.get("difficulty") and not json_mode:
        print(C.warn("Could not fetch live difficulty — using default 127T"))

    # Run comparison
    results = sm.compare_rentals(
        budget, difficulty, duration,
        braiins_price, mrr_price,
        objective=objective,
        auto_fetch=False,
    )

    if json_mode:
        return {
            "budget_btc": budget,
            "duration_hours": duration,
            "difficulty": difficulty,
            "braiins_price_btc_per_ph_day": braiins_price,
            "mrr_price_btc_per_ph_day": mrr_price,
            "objective": objective,
            "options": results,
        }

    print()
    print(C.ok(f"Budget: {budget} BTC | Duration: {duration}h | Difficulty: {_fmt_diff_human(difficulty)}"))

    if not results:
        print()
        print(C.err("No valid rental options — all price sources failed."))
        if mrr_price is None and braiins_price is None:
            print(C.warn("Tip: set MRR_API_KEY/MRR_API_SECRET env vars for live MRR pricing"))
        return

    # Check for API error entry
    if len(results) == 1 and results[0].get("api_status") == "error":
        print()
        print(C.err("Could not fetch rental prices:"))
        for err in results[0].get("api_errors", []):
            print(f"        {err}")
        print()
        print(C.warn("Provide prices manually: --braiins <price> --mrr <price> (BTC/PH/day)"))
        return

    print()
    header = f"  {'Platform':<22s}  {'Price/PH/d':>10s}   {'Hashpower':>10s}  {'P(block)':>9s}  {'Expected':>12s}   {'EV(BTC)':>10s}"
    sep    = f"  {'─'*22}  {'─'*10}   {'─'*10}  {'─'*9}  {'─'*12}   {'─'*10}"
    print(header)
    print(sep)
    for r in results:
        print(
            f"  {r['platform']:<22s}  {r['price_btc_per_ph_day']:>10.6f}   "
            f"{r['hashpower_ph']:>8.2f}PH  {r['p_block_pct']:>7.4f}%  "
            f"{r['expected_time_days']:>10.0f}d  {r['ev_btc']:>+10.6f}"
        )

    print()
    if len(results) == 1 and "MRR" not in results[0]["platform"] and mrr_price is None:
        print(C.warn("Note: MRR was skipped (no credentials or API error). Set MRR_API_KEY/MRR_API_SECRET to include MRR in comparison."))
    if results[0]["ev_btc"] < 0:
        print(C.warn("All options have negative EV. Solo mining is a lottery."))
    else:
        print(C.ok(f"Best option: {results[0]['platform']} (EV={results[0]['ev_btc']:+.6f} BTC)"))

    print()


def cmd_ask(args):
    """Handle free-text natural language queries with forgiving keyword parsing.
    Understands casual Portuguese, English, typos, slang, and mixed language."""
    query = " ".join(args)
    if not query:
        print(C.err("Usage: ask <your question>"))
        print(C.hint("Examples: ask qual a chance de achar bloco? | ask what's the difficulty?"))
        return

    print()
    print(f"{C.MUTED}entendi: {C.RST}\"{query[:80]}\"")

    query_lower = query.lower().strip()
    import re
    # Normalize for keyword matching: strip sentence punctuation but preserve decimal dots
    # Replace ?, !, ;, : and commas that aren't part of numbers (e.g., "0,01")
    q = re.sub(r'[?!;:]', ' ', query_lower)
    # Preserve dots in numbers (e.g., "0.01 btc") but strip trailing sentence dots
    q = re.sub(r'\.(?!\d)', ' ', q)

    # ══ Check patterns: compare first (most specific), then calc, network, status, help

    # ── Pattern: compare / rental / aluguel ──
    compare_kw = [
        # Portuguese
        "compara", "comparar", "comparação", "comparacao", "compare",
        "aluguel", "alugar", "aluga", "rental", "alocação", "alocacao",
        "braiins", "brain", "brains", "brians",
        "mrr", "miningrigrentals", "mining rig", "miningrig",
        "qual melhor", "qual vale mais", "qual compensa",
        "vale a pena", "compensa", "mais barato", "melhor opção",
        "custo", "orçamento", "orcamento", "budget",
        # English
        "which one", "better", "worth it", "cheaper", "best option",
        "rent", "renting",
    ]
    if any(k in q for k in compare_kw):
        btc_match = re.search(r'(\d+\.?\d*)\s*(btc|sat|sats|bitcoin)', q, re.IGNORECASE)
        dur_match = re.search(r'(\d+\.?\d*)\s*(h|hour|hr|hours|horas|hora|d|day|days|dia|dias)', q)
        if btc_match and dur_match:
            budget = btc_match.group(1)
            dur_val = float(dur_match.group(1))
            dur_unit = dur_match.group(2).lower()
            if dur_unit in ('d', 'day', 'days', 'dia', 'dias'):
                dur_val *= 24
            print()
            print(C.ok(f"Entendi: budget={budget} BTC, duration={dur_val:.0f}h"))
            cmd_compare(["--budget", budget, "--duration", str(int(dur_val))])
            return

        print()
        print(C.ok("Entendi que é pergunta sobre aluguel de hashrate"))
        print(C.warn("Preciso de orçamento e duração pra comparar. Tente algo como:"))
        print(C.hint("ask compara braiins vs mrr com 0.01 btc por 24h"))
        print(C.hint("Ou use: compare --budget 0.01 --duration 24h"))
        return

    # ── Pattern: compare / rental / aluguel (check FIRST — more specific than generic price/difficulty) ──
    network_kw = [
        # Portuguese
        "rede", "dificuldade", "difculdade", "dificudade", "dificul", "network",
        "preco", "preço", "cotação", "cotacao", "quanto ta", "quanto tá",
        "ta valendo", "tá valendo", "valor", "preço btc", "preco btc",
        "bitcoin price", "btc price", "btc/usd", "btc/brl",
        # English
        "difficulty", "dificulty", "diff", "current", "price", "btc",
        "what's the", "what is the", "how much",
        # Common queries
        "como ta", "como tá", "como esta", "como está",
        "me mostra", "mostra", "show me", "show",
        "da rede", "atual", "hoje", "now", "today",
    ]
    if any(k in q for k in network_kw):
        cmd_network()
        return

    # ── Pattern: calc / probability / chance ──
    calc_kw = [
        # Portuguese
        "calcular", "calcula", "calc", "calulo", "calculo", "cálculo",
        "probabilidade", "probabilida", "prob", "chance", "chances",
        "qual a chance", "quais as chances", "quanto tempo", "tempo esperado",
        "acha bloco", "achar bloco", "encontra bloco", "encontrar bloco",
        "minerar", "minerando", "mineração", "mineracao",
        "quantos blocos", "quantos bloco",
        # English
        "probability", "probablity", "probabilty", "odds",
        "chance of", "chances of", "likely", "likelihood",
        "how long", "expected time", "how many",
        "find a block", "finding", "block chance",
        # Units (signal it's a mining calc question)
        "th/s", "ph/s", "eh/s", "gh/s", "mh/s",
        "ths", "phs", "ehs", "ths",
        "th ", "ph ", "eh ",
        "hashrate", "hash rate", "hash",
        # Common queries
        "se eu", "com ", "usando", "durante", "por ",
        "solo", "solo mining",
    ]
    if any(k in q for k in calc_kw):
        # Try to extract hashrate and duration from the query
        hr_match = re.search(r'(\d+\.?\d*)\s*(th/s|ph/s|eh/s|gh/s|mh/s|th|ph|eh|gh|mh)', q, re.IGNORECASE)
        dur_match = re.search(r'(\d+\.?\d*)\s*(h|hour|hr|hours|horas|hora|d|day|days|dia|dias|w|week|weeks|semana|semanas)', q)
        if hr_match and dur_match:
            hashrate = hr_match.group(1) + hr_match.group(2).upper().replace('/S', '')
            dur_val = float(dur_match.group(1))
            dur_unit = dur_match.group(2).lower()
            if dur_unit in ('d', 'day', 'days', 'dia', 'dias'):
                dur_val *= 24
            elif dur_unit in ('w', 'week', 'weeks', 'semana', 'semanas'):
                dur_val *= 168
            print()
            print(C.ok(f"Entendi: hashrate={hashrate}, duration={dur_val:.0f}h"))
            cmd_calc(["--hashrate", hashrate, "--duration", str(int(dur_val))])
            return

        print()
        print(C.ok("Entendi que é pergunta sobre probabilidade de mineração"))
        print(C.warn("Preciso de hashrate e duração pra calcular. Tente algo como:"))
        print(C.hint("ask qual a chance de achar bloco com 225TH por 24h?"))
        print(C.hint("Ou use: calc --hashrate 225TH --duration 24h"))
        return

    # ── Pattern: status / dashboard / how am I doing ──
    status_kw = [
        # Portuguese
        "status", "dashboard", "resumo", "sumario", "sumário",
        "como estou", "como eu to", "como eu tô", "como ta minha",
        "minha mineração", "minha mineracao", "meu minerador",
        "ta funcionando", "tá funcionando", "funcionando",
        "online", "offline", "conectado",
        # English
        "how am i", "how's my", "am i mining", "my miner",
        "stats", "summary", "overview",
    ]
    if any(k in q for k in status_kw):
        cmd_status()
        return

    # ── Pattern: help ──
    help_kw = ["help", "ajuda", "ajudar", "socorro", "comandos", "commands", "o que faz", "o que vc faz"]
    if any(k in q for k in help_kw):
        cmd_help()
        return

    # ── Fallback: can't parse, but be friendly ──
    print()
    print(C.warn("Não entendi exatamente o que você quer, mas posso ajudar com:"))
    print(f"  {C.GREEN}•{C.RST} Digite '{C.GREEN}network{C.RST}' — dificuldade e preço do BTC agora")
    print(f"  {C.GREEN}•{C.RST} Digite '{C.GREEN}status{C.RST}' — resumo completo da sua mineração")
    print(f"  {C.GREEN}•{C.RST} Digite '{C.GREEN}calc --hashrate 225TH --duration 24h{C.RST}' — chance de achar bloco")
    print(f"  {C.GREEN}•{C.RST} Digite '{C.GREEN}compare --budget 0.01 --duration 24h{C.RST}' — comparar aluguel")
    print(f"  {C.GREEN}•{C.RST} Digite '{C.GREEN}help{C.RST}' — todos os comandos")
    print(f"  {C.GREEN}•{C.RST} Ou me pergunte de outro jeito: 'qual a chance de achar bloco com 500th por 7 dias?'")


def cmd_chat(args=None):
    """Enter continuous chat mode — every line is a natural language query.
    Type 'exit', 'sair', or 'voltar' to return to the main terminal."""
    print()
    print(C.ok("Modo conversa ativado!"))
    print(C.hint("Digite qualquer pergunta em linguagem natural. Ex: 'qual a chance de achar bloco com 500th?'"))
    print(C.hint(f"Digite '{C.GREEN}exit{C.RST}', '{C.GREEN}sair{C.RST}' ou '{C.GREEN}voltar{C.RST}' para retornar ao terminal principal."))
    print()

    exit_words = {"exit", "quit", "q", "sair", "voltar", "back", "menu", "stop", "fim"}

    while True:
        try:
            line = input(CHAT_PROMPT)
        except (EOFError, KeyboardInterrupt):
            print()
            print()
            print(C.ok("Voltando ao terminal principal..."))
            print()
            break

        line = line.strip()
        if not line:
            print(C.hint("Digite uma pergunta ou 'sair' para voltar."))
            continue

        if line.lower() in exit_words:
            print()
            print(C.ok("Voltando ao terminal principal..."))
            print()
            break

        # Process as natural language query — reuse cmd_ask without the "ask" prompt line
        query_lower = line.lower().strip()
        import re
        q = re.sub(r'[?!;:]', ' ', query_lower)
        q = re.sub(r'\.(?!\d)', ' ', q)

        compare_kw = [
            "compara", "comparar", "comparação", "comparacao", "compare",
            "aluguel", "alugar", "aluga", "rental", "alocação", "alocacao",
            "braiins", "brain", "brains", "brians",
            "mrr", "miningrigrentals", "mining rig", "miningrig",
            "qual melhor", "qual vale mais", "qual compensa",
            "vale a pena", "compensa", "mais barato", "melhor opção",
            "custo", "orçamento", "orcamento", "budget",
            "which one", "better", "worth it", "cheaper", "best option",
            "rent", "renting",
        ]
        network_kw = [
            "rede", "dificuldade", "difculdade", "dificudade", "dificul", "network",
            "preco", "preço", "cotação", "cotacao", "quanto ta", "quanto tá",
            "ta valendo", "tá valendo", "valor", "preço btc", "preco btc",
            "bitcoin price", "btc price", "btc/usd", "btc/brl",
            "difficulty", "dificulty", "diff", "current", "price", "btc",
            "what's the", "what is the", "how much",
            "como ta", "como tá", "como esta", "como está",
            "me mostra", "mostra", "show me", "show",
            "da rede", "atual", "hoje", "now", "today",
        ]
        calc_kw = [
            "calcular", "calcula", "calc", "calulo", "calculo", "cálculo",
            "probabilidade", "probabilida", "prob", "chance", "chances",
            "qual a chance", "quais as chances", "quanto tempo", "tempo esperado",
            "acha bloco", "achar bloco", "encontra bloco", "encontrar bloco",
            "minerar", "minerando", "mineração", "mineracao",
            "quantos blocos", "quantos bloco",
            "probability", "probablity", "probabilty", "odds",
            "chance of", "chances of", "likely", "likelihood",
            "how long", "expected time", "how many",
            "find a block", "finding", "block chance",
            "th/s", "ph/s", "eh/s", "gh/s", "mh/s",
            "ths", "phs", "ehs",
            "th ", "ph ", "eh ",
            "hashrate", "hash rate", "hash",
            "se eu", "com ", "usando", "durante", "por ",
            "solo", "solo mining",
        ]
        status_kw = [
            "status", "dashboard", "resumo", "sumario", "sumário",
            "como estou", "como eu to", "como eu tô", "como ta minha",
            "minha mineração", "minha mineracao", "meu minerador",
            "ta funcionando", "tá funcionando", "funcionando",
            "online", "offline", "conectado",
            "how am i", "how's my", "am i mining", "my miner",
            "stats", "summary", "overview",
        ]
        help_kw = ["help", "ajuda", "ajudar", "socorro", "comandos", "commands", "o que faz", "o que vc faz"]

        # ── Compare ──
        if any(k in q for k in compare_kw):
            btc_match = re.search(r'(\d+\.?\d*)\s*(btc|sat|sats|bitcoin)', q, re.IGNORECASE)
            dur_match = re.search(r'(\d+\.?\d*)\s*(h|hour|hr|hours|horas|hora|d|day|days|dia|dias)', q)
            if btc_match and dur_match:
                budget = btc_match.group(1)
                dur_val = float(dur_match.group(1))
                dur_unit = dur_match.group(2).lower()
                if dur_unit in ('d', 'day', 'days', 'dia', 'dias'):
                    dur_val *= 24
                print()
                print(C.ok(f"Entendi: budget={budget} BTC, duration={dur_val:.0f}h"))
                cmd_compare(["--budget", budget, "--duration", str(int(dur_val))])
            else:
                print()
                print(C.warn("Consegui identificar que é sobre aluguel. Me passe orçamento e duração."))
                print(C.hint("Ex: 'compara 0.01 btc por 24h'"))
            continue

        # ── Status ──
        if any(k in q for k in status_kw):
            cmd_status()
            continue

        # ── Calc ──
        if any(k in q for k in calc_kw):
            hr_match = re.search(r'(\d+\.?\d*)\s*(th/s|ph/s|eh/s|gh/s|mh/s|th|ph|eh|gh|mh)', q, re.IGNORECASE)
            dur_match = re.search(r'(\d+\.?\d*)\s*(h|hour|hr|hours|horas|hora|d|day|days|dia|dias|w|week|weeks|semana|semanas)', q)
            if hr_match and dur_match:
                hashrate = hr_match.group(1) + hr_match.group(2).upper().replace('/S', '')
                dur_val = float(dur_match.group(1))
                dur_unit = dur_match.group(2).lower()
                if dur_unit in ('d', 'day', 'days', 'dia', 'dias'):
                    dur_val *= 24
                elif dur_unit in ('w', 'week', 'weeks', 'semana', 'semanas'):
                    dur_val *= 168
                print()
                print(C.ok(f"Entendi: hashrate={hashrate}, duration={dur_val:.0f}h"))
                cmd_calc(["--hashrate", hashrate, "--duration", str(int(dur_val))])
            else:
                print()
                print(C.warn("Consegui identificar que é sobre mineração. Me passe hashrate e tempo."))
                print(C.hint("Ex: 'chance com 500th por 7 dias'"))
            continue

        # ── Network ──
        if any(k in q for k in network_kw):
            cmd_network()
            continue

        # ── Help ──
        if any(k in q for k in help_kw):
            cmd_help()
            continue

        # ── Fallback ──
        print()
        print(C.warn("Não entendi. Tente:"))
        print(f"  {C.GREEN}•{C.RST} '{C.GREEN}network{C.RST}' — dificuldade e preço")
        print(f"  {C.GREEN}•{C.RST} '{C.GREEN}status{C.RST}' — resumo da mineração")
        print(f"  {C.GREEN}•{C.RST} 'chance com 500th por 7 dias' — probabilidade")
        print(f"  {C.GREEN}•{C.RST} '{C.GREEN}compara 0.01 btc 24h{C.RST}' — aluguel")
        print()


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _fmt_diff_human(v):
    """Format difficulty number to human-readable string (e.g. '127.17 T')."""
    if not v or not math.isfinite(v):
        return "0"
    units = ["", "K", "M", "G", "T", "P", "E"]
    i = 0
    x = abs(v)
    while x >= 1000 and i < len(units) - 1:
        x /= 1000
        i += 1
    return f"{x:.{0 if x >= 100 else 2}f} {units[i]}".strip()


def _parse_diff_float(s):
    """Parse difficulty string like '127T', '110.5 P', '127.17' to float."""
    s = str(s).strip().upper()
    mult_map = {"": 1, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18}
    for unit, mult in mult_map.items():
        if s.endswith(unit):
            num = s[:-len(unit)].strip() if unit else s
            try:
                return float(num) * mult
            except ValueError:
                return 127e12  # fallback
    try:
        return float(s)
    except ValueError:
        print(f"{C.WARN}Invalid difficulty string '{s}' — using default 127T{C.RST}")
        return 127e12


def _fmt_hashrate_human(v):
    """Format hashrate in H/s to human-readable string (e.g. '225 TH/s')."""
    if not v or not math.isfinite(v):
        return "0 H/s"
    v = abs(v)
    units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"]
    i = 0
    while v >= 1000 and i < len(units) - 1:
        v /= 1000
        i += 1
    return f"{v:.{0 if v >= 100 else 1}f} {units[i]}"


def _coerce_float(v):
    """Safely convert a value to float, handling strings with units like '1.5 PH/s'."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (ValueError, TypeError):
        pass
    import re
    m = re.match(r'([\d.,]+)\s*([EPTGMk]?)', str(v).strip().upper())
    if m:
        num = float(m.group(1).replace(',', ''))
        unit = m.group(2).upper()
        mult = {'E': 1e18, 'P': 1e15, 'T': 1e12, 'G': 1e9, 'M': 1e6, 'K': 1e3, '': 1}
        return num * mult.get(unit, 1)
    return 0


def _fmt_uptime_human(s):
    """Format seconds to human-readable uptime (e.g. '3d 12h')."""
    if not s:
        return "\u2014"
    try:
        s = int(s)
    except (ValueError, TypeError):
        return str(s)
    if s < 60:
        return f"{s}s"
    d = s // 86400
    h = (s % 86400) // 3600
    m = (s % 3600) // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:
        parts.append(f"{m}m")
    return " ".join(parts) or "0m"


def _parse_command(line):
    """Split a command line into tokens, respecting quoted strings."""
    import shlex
    try:
        return shlex.split(line)
    except ValueError:
        # Fallback: simple split
        return line.split()


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN REPL
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """Entry point for the interactive CLI REPL."""
    _setup_readline()

    print(BANNER)

    # Commands that take args
    _ARGS_COMMANDS = {"calc", "compare", "ask", "query"}
    # Commands that support --json mode
    _JSON_COMMANDS = {"network", "status", "calc", "compare"}
    # Commands that open a sub-loop (no text piping, no --json)
    _SUBLOOP_COMMANDS = {"chat", "conversa", "conversar", "talk"}

    # Dispatch table: verb → handler function (no lambdas)
    commands = {
        "help": cmd_help,
        "status": cmd_status,
        "network": cmd_network,
        "calc": cmd_calc,
        "compare": cmd_compare,
        "ask": cmd_ask,
        "query": cmd_ask,
        "chat": cmd_chat,
        "conversa": cmd_chat,
        "conversar": cmd_chat,
        "talk": cmd_chat,
        "clear": cmd_clear,
        "cls": cmd_clear,
    }

    while True:
        try:
            raw_line = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            print()
            break

        line = raw_line.strip()
        if not line:
            continue

        # ── Parse pipe redirect (> filename) ──
        out_file = None
        if " >" in line:
            pipe_idx = line.rfind(" >")
            out_file = line[pipe_idx + 2:].strip()
            line = line[:pipe_idx].strip()

        tokens = _parse_command(line)
        verb = tokens[0].lower() if tokens else ""
        args = tokens[1:] if len(tokens) > 1 else []

        if verb in ("exit", "quit", "q"):
            print(f"{C.MUTED}exiting...{C.RST}")
            break

        # ── Parse --json flag ──
        json_mode = "--json" in args
        if json_mode:
            args = [a for a in args if a != "--json"]

        if verb in commands:
            # Subloop commands (chat, conversa) handle their own I/O — skip piping/JSON
            if verb in _SUBLOOP_COMMANDS:
                try:
                    commands[verb]()
                except Exception as e:
                    print(C.err(f"Command failed: {e}"))
                continue

            try:
                result = None
                buf = io.StringIO()

                # Run command (with stdout capture if piping)
                if out_file:
                    with redirect_stdout(buf):
                        result = _dispatch(verb, args, json_mode, commands, _ARGS_COMMANDS, _JSON_COMMANDS)
                else:
                    result = _dispatch(verb, args, json_mode, commands, _ARGS_COMMANDS, _JSON_COMMANDS)

                # Handle JSON + piping: write JSON directly to file
                if json_mode and result is not None:
                    if out_file:
                        target = os.path.expanduser(out_file)
                        with open(target, "w") as f:
                            json.dump(result, f, indent=2, default=str)
                        print(f"{C.ok(f'Saved JSON to {out_file}')}")
                    else:
                        print(json.dumps(result, indent=2, default=str))
                # Handle text piping: write captured stdout to file
                elif out_file:
                    captured = buf.getvalue()
                    target = os.path.expanduser(out_file)
                    with open(target, "w") as f:
                        f.write(captured)
                    print(f"{C.ok(f'Saved {len(captured)} bytes to {out_file}')}")

            except Exception as e:
                print(C.err(f"Command failed: {e}"))
        else:
            # Not a known command — treat as natural language query (no 'ask' prefix needed)
            cmd_ask(tokens)


def _dispatch(verb, args, json_mode, commands, _ARGS_COMMANDS, _JSON_COMMANDS):
    """Call the command handler with appropriate arguments.
    Returns the handler's result (dict for json_mode, None otherwise)."""
    handler = commands[verb]
    if json_mode and verb in _JSON_COMMANDS:
        if verb in _ARGS_COMMANDS:
            return handler(args, json_mode=True)
        return handler(json_mode=True)
    if verb in _ARGS_COMMANDS:
        return handler(args)
    return handler()


if __name__ == "__main__":
    main()
