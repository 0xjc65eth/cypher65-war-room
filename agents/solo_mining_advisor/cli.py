"""
CYPHER SOLO MINING ADVISOR — Interactive CLI
=============================================
A proper terminal REPL for solo mining calculations.

Usage:
    python3 -m agents.solo_mining_advisor.cli

Commands:
    network                          — Show live network difficulty + BTC price
    calc --hashrate <H> --duration <h> [--difficulty <D>]
                                     — Calculate block probability
    compare --budget <BTC> --duration <h> [--braiins <p>] [--mrr <p>]
                                     — Compare Braiins vs MRR rental options
    ask <free-text query>            — Natural language mining query
    help                             — Show this help
    clear                            — Clear the screen
    exit / quit                      — Exit the terminal
"""

import os
import math
import atexit
from pathlib import Path

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
        "network", "calc", "compare", "ask", "query",
        "help", "clear", "cls", "exit", "quit",
    ],
    # per-command flags and value hints
    "network": [],
    "calc": ["--hashrate", "--duration", "--difficulty"],
    "compare": ["--budget", "--duration", "--braiins", "--mrr", "--objective"],
    "ask": [],
    "query": [],
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

  Type {C.GREEN}help{C.RST} for commands, {C.GREEN}exit{C.RST} to quit.
"""

PROMPT = f"{C.GREEN}julio@cypher{C.RST}:{C.BLUE}~/solo-mining{C.RST}$ "


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
    print(f"  {C.GREEN}network{C.RST}")
    print(f"       Show live Bitcoin network difficulty + BTC price")
    print()
    print(f"  {C.GREEN}calc --hashrate <value> --duration <h>{C.RST} {C.MUTED}[--difficulty <d>]{C.RST}")
    print(f"       Calculate solo mining probability (auto-fetches live difficulty)")
    print(f"       Examples: calc --hashrate 225TH --duration 24h")
    print(f"                 calc --hashrate 1.5PH --duration 168h --difficulty 127T")
    print()
    print(f"  {C.GREEN}compare --budget <btc> --duration <h>{C.RST} {C.MUTED}[--braiins <p>] [--mrr <p>]{C.RST}")
    print(f"       Compare Braiins vs MRR rental options (auto-fetches live prices)")
    print(f"       Example: compare --budget 0.01 --duration 24h")
    print()
    print(f"  {C.GREEN}ask <free-text query>{C.RST}")
    print(f"       Natural language mining query")
    print(f"       Example: ask what is the current network difficulty?")
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


def cmd_network():
    """Fetch and display live network difficulty + BTC price using agent tools."""
    execute_tool = _get_execute_tool()

    print()
    print(f"{C.MUTED}fetching live data from agent tools...{C.RST}")

    # Fetch difficulty
    diff_result = execute_tool("get_network_difficulty")
    # Fetch BTC price
    price_result = execute_tool("get_btc_price", {"currencies": "usd,brl"})

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


def cmd_calc(args):
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
        print()
        print(f"{C.MUTED}fetching live difficulty from agent tools...{C.RST}")
        diff_result = execute_tool("get_network_difficulty")
        if diff_result.get("difficulty"):
            difficulty = diff_result["difficulty"]
            print(C.ok(f"Using live difficulty: {_fmt_diff_human(difficulty)} ({diff_result.get('source', 'agent')})"))
        else:
            print(C.warn("Could not fetch live difficulty — using default 127T"))
            difficulty = 127e12  # ~127T fallback
    else:
        # Parse difficulty string
        difficulty = _parse_diff_float(difficulty)

    hashrate_hs = sm._parse_hashrate(hashrate)
    duration_seconds = duration * 3600

    # Run calculations
    prob = sm.calc_block_probability(hashrate_hs, difficulty, duration_seconds)
    exp_time = sm.calc_expected_time(hashrate_hs, difficulty)
    best_diff = sm.calc_best_diff_expected(hashrate_hs, duration_seconds)

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


def cmd_compare(args):
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
        print()
        print(f"{C.MUTED}fetching live rental prices from agent tools...{C.RST}")

    if braiins_price is None:
        result = execute_tool("get_braiins_orderbook")
        if result.get("price_btc_per_ph_day") is not None:
            braiins_price = result["price_btc_per_ph_day"]
            print(C.ok(f"Braiins: {braiins_price:.8f} BTC/PH/day ({result.get('available_asks', '?')} asks)"))
        else:
            print(C.warn(f"Braiins unavailable: {result.get('error', 'no data')}"))

    if mrr_price is None:
        result = execute_tool("get_mrr_listings")
        if result.get("price_btc_per_ph_day") is not None:
            mrr_price = result["price_btc_per_ph_day"]
            print(C.ok(f"MRR: {mrr_price:.8f} BTC/PH/day ({result.get('total_listings', '?')} listings)"))
        elif result.get("needs_auth"):
            print(C.warn(f"MRR: {result.get('error', 'credentials required')}"))
        else:
            print(C.warn(f"MRR unavailable: {result.get('error', 'no data')}"))

    # Get difficulty
    diff_result = execute_tool("get_network_difficulty")
    difficulty = diff_result.get("difficulty", 127e12)
    if not diff_result.get("difficulty"):
        print(C.warn("Could not fetch live difficulty — using default 127T"))

    # Run comparison
    results = sm.compare_rentals(
        budget, difficulty, duration,
        braiins_price, mrr_price,
        objective=objective,
        auto_fetch=False,  # Already fetched above
    )

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
    """Handle free-text natural language queries via keyword parsing."""
    query = " ".join(args)
    if not query:
        print(C.err("Usage: ask <free-text query>"))
        print(C.hint("Example: ask what is the current network difficulty?"))
        return

    print()
    print(f"{C.MUTED}querying agent: {C.RST}\"{query[:80]}\"")

    query_lower = query.lower()

    # Pattern 1: network/difficulty/price
    network_kw = ["network", "difficulty", "difficult", "price", "btc", "bitcoin price", "current"]
    if any(k in query_lower for k in network_kw):
        cmd_network()
        return

    # Pattern 2: calc/probability
    calc_kw = ["calc", "calculate", "probability", "prob", "chance", "odds", "hashrate", "th/s", "ph/s", "eh/s"]
    if any(k in query_lower for k in calc_kw):
        print()
        print(C.ok("Calculation query detected"))
        print(C.warn("Natural-language parsing is limited — use structured command for precise results"))
        print(C.hint("Example: calc --hashrate 225TH --duration 24h"))
        return

    # Pattern 3: compare/rental
    compare_kw = ["compare", "rental", "rent", "braiins", "mrr", "miningrigrentals", "which", "better", "worth"]
    if any(k in query_lower for k in compare_kw):
        print()
        print(C.ok("Comparison query detected"))
        print(C.warn("Natural-language parsing is limited — use structured command for precise results"))
        print(C.hint("Example: compare --budget 0.01 --duration 24h"))
        return

    # Fallback
    print()
    print(C.warn("Could not parse query — try one of:"))
    print(f"  {C.GREEN}•{C.RST} Type '{C.GREEN}network{C.RST}' for live difficulty & BTC price")
    print(f"  {C.GREEN}•{C.RST} Type '{C.GREEN}calc --hashrate <value> --duration <h>{C.RST}' for mining probabilities")
    print(f"  {C.GREEN}•{C.RST} Type '{C.GREEN}compare --budget <btc> --duration <h>{C.RST}' to compare rental options")
    print(f"  {C.GREEN}•{C.RST} Type '{C.GREEN}help{C.RST}' for full command reference")


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

    # Dispatch table
    commands = {
        "help": lambda _: cmd_help(),
        "network": lambda _: cmd_network(),
        "calc": lambda args: cmd_calc(args),
        "compare": lambda args: cmd_compare(args),
        "ask": lambda args: cmd_ask(args),
        "query": lambda args: cmd_ask(args),  # alias
        "clear": lambda _: cmd_clear(),
        "cls": lambda _: cmd_clear(),
    }

    while True:
        try:
            line = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        tokens = _parse_command(line)
        verb = tokens[0].lower() if tokens else ""
        args = tokens[1:] if len(tokens) > 1 else []

        if verb in ("exit", "quit", "q"):
            print(f"{C.MUTED}exiting...{C.RST}")
            break

        if verb in commands:
            try:
                commands[verb](args)
            except Exception as e:
                print(C.err(f"Command failed: {e}"))
        else:
            print(C.err(f"Unknown command: {C.RED}{verb}{C.RST}. Type {C.GREEN}help{C.RST} for available commands."))


if __name__ == "__main__":
    main()
