#!/usr/bin/env python3
"""check-monkeypatch-targets.py — guard de alvo de patch órfão (CI).

Um patch de teste só intercepta o código se o nome patcheado for **usado pelo
próprio módulo** que está sendo alvo. Quando um símbolo muda de casa, o módulo
antigo continua expondo o nome via re-export — e aí:

    monkeypatch.setattr(services.user_polling, "_fetch_json", fake)

passa a ser um **no-op**: o `_fetch_json` que o código realmente chama é
resolvido nos globals de `services.snapshot_assembly`. Nada falha. O teste
apenas deixa de injetar o fake.

Foi exatamente o que aconteceu no PR B3 (#502): `tests/test_anti_mock.py`
patcheava `services.user_polling._fetch_*`, os patches deixaram de interceptar,
o `_build_snapshot` foi à rede de verdade, caiu no `except` e devolveu o
snapshot default — e as asserções continuaram satisfeitas pelos defaults. Um
teste que passou a não testar nada, com a suíte tocando a rede.

O guard é estático (só AST, sem importar o alvo) e usa uma definição precisa de
"dono": o módulo alvo só é dono de `N` se `N` for

  * definido no próprio módulo (função/classe/atribuição/for/with/except), OU
  * referenciado em algum lugar do próprio módulo (o lookup de global de um nome
    importado acontece no dicionário do módulo, então patch nele funciona).

Nome que o módulo **só importa e nunca usa** (re-export puro) NÃO é dele —
patchear ali é órfão.

Uso:
    python scripts/check-monkeypatch-targets.py
    python scripts/check-monkeypatch-targets.py --list      # só lista os alvos

Escape hatch para uma exceção real e documentada (na linha da chamada ou na
linha imediatamente acima):

    monkeypatch.setattr(up, "_x", fake)  # orphan-patch-ok: <motivo>

Exit codes:
    0 — nenhum alvo órfão
    1 — alvo(s) órfão(s) encontrados
    2 — erro de execução
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Módulos first-party (o que o repo possui). Diretórios + arquivos de topo.
FIRST_PARTY_DIRS = ["services", "routes", "axe_fleet", "core", "agents"]
FIRST_PARTY_FILES = ["app.py", "helpers.py", "solo_mining.py"]

OK_MARKER = "orphan-patch-ok"


class Violation:
    __slots__ = ("test_file", "lineno", "module", "name")

    def __init__(self, test_file: str, lineno: int, module: str, name: str):
        self.test_file = test_file
        self.lineno = lineno
        self.module = module
        self.name = name

    def __str__(self) -> str:
        return (
            f"{self.test_file}:{self.lineno}: patch em {self.module}.{self.name} "
            f"— o módulo não é dono desse nome (re-export / só import), então o "
            f"patch não intercepta"
        )


# ── Índice de módulos first-party ──────────────────────────────────────────


def module_index(root: Path) -> dict[str, Path]:
    """dotted module name → arquivo .py (só first-party)."""
    index: dict[str, Path] = {}
    for name in FIRST_PARTY_FILES:
        path = root / name
        if path.is_file():
            index[name[: -len(".py")]] = path
    for dirname in FIRST_PARTY_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if not parts:
                continue
            index[".".join(parts)] = path
    return index


# ── Dono do nome: definido OU usado no próprio módulo ──────────────────────


def _bind_target(node: ast.AST, out: set[str]) -> None:
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            _bind_target(elt, out)
    elif isinstance(node, ast.Starred):
        _bind_target(node.value, out)


def _module_level_bindings(body: list[ast.stmt], own: set[str]) -> None:
    """Nomes ligados no nível do módulo (desce em If/Try/With/For, não em defs)."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            own.add(stmt.name)  # não desce: o corpo tem binds locais
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                _bind_target(target, own)
        elif isinstance(stmt, ast.AnnAssign):
            _bind_target(stmt.target, own)
        elif isinstance(stmt, ast.AugAssign):
            _bind_target(stmt.target, own)
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            _bind_target(stmt.target, own)
            _module_level_bindings(stmt.body, own)
            _module_level_bindings(stmt.orelse, own)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if item.optional_vars is not None:
                    _bind_target(item.optional_vars, own)
            _module_level_bindings(stmt.body, own)
        elif isinstance(stmt, ast.If):
            _module_level_bindings(stmt.body, own)
            _module_level_bindings(stmt.orelse, own)
        elif isinstance(stmt, ast.Try):
            _module_level_bindings(stmt.body, own)
            _module_level_bindings(stmt.orelse, own)
            _module_level_bindings(stmt.finalbody, own)
            for handler in stmt.handlers:
                if handler.name:
                    own.add(handler.name)
                _module_level_bindings(handler.body, own)


def owned_names(tree: ast.Module) -> set[str]:
    """Nomes que o módulo possui: definidos por ele OU usados por ele.

    Nomes vindos SÓ de import/from-import e nunca usados no corpo ficam de fora
    — são re-exports, e patchear o re-export não afeta o dono real.
    """
    own: set[str] = set()
    _module_level_bindings(tree.body, own)
    used = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            own.update(node.names)
    return own | used


# ── Extração dos alvos de patch nos testes ─────────────────────────────────


def _test_alias_map(tree: ast.Module) -> dict[str, str]:
    """Alias local → caminho dotted do módulo importado."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                aliases[local] = alias.name if alias.asname else alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for alias in node.names:
                    local = alias.asname or alias.name
                    aliases[local] = f"{node.module}.{alias.name}"
    return aliases


def _dotted(node: ast.AST) -> str | None:
    """`a.b.c` → "a.b.c" (só Name/Attribute). Senão None."""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _str_arg(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _targets_in_call(node: ast.Call) -> list[tuple[str, tuple[int, int]]]:
    """Extrai (dotted_expr, arg_node) dos idiomas de patch suportados."""
    func = node.func
    out: list[tuple[str, ast.AST]] = []
    fname = func.attr if isinstance(func, ast.Attribute) else None

    if fname == "setattr" and len(node.args) >= 2:  # monkeypatch.setattr/…
        out.append((_dotted(node.args[0]) or "", node.args[1]))
    elif fname == "object" and len(node.args) >= 2:  # patch.object/mocker.patch.object
        out.append((_dotted(node.args[0]) or "", node.args[1]))
    elif fname == "patch" and node.args:  # mock.patch("a.b.c")
        out.append(("", node.args[0]))
    elif isinstance(func, ast.Name) and func.id == "patch" and node.args:
        out.append(("", node.args[0]))

    return [(dotted, arg) for dotted, arg in out]


def resolve_module(
    dotted_expr: str,
    literal: str | None,
    aliases: dict[str, str],
    index: dict[str, Path],
) -> tuple[str, str] | None:
    """Resolve (módulo, nome) a partir do alvo do patch. None se não é first-party."""
    if literal is not None and not dotted_expr:
        # Forma string: "pkg.mod.nome" — o módulo é tudo antes do último ponto.
        if "." not in literal:
            return None
        module, name = literal.rsplit(".", 1)
        return (module, name) if module in index else None

    if not dotted_expr or literal is None:
        return None

    # Forma expressão: resolve o alias e exige um MÓDULO puro (sem sobra).
    head, _, rest = dotted_expr.partition(".")
    base = aliases.get(head, head)
    full = f"{base}.{rest}" if rest else base
    if full in index:
        return (full, literal)
    return None


def _has_escape(source_lines: list[str], first: int, last: int) -> bool:
    """`# orphan-patch-ok: …` em qualquer linha da chamada ou na de cima.

    O idioma real é uma chamada multi-linha (black quebra o setattr longo),
    então a janela cobre do início ao fim do `Call` — mais a linha anterior.
    """
    start = max(0, first - 2)
    for idx in range(start, min(last + 1, len(source_lines))):
        if OK_MARKER in source_lines[idx]:
            return True
    return False


def find_violations(root: Path) -> list[Violation]:
    index = module_index(root)
    owned: dict[str, set[str]] = {}
    for module, path in index.items():
        try:
            owned[module] = owned_names(ast.parse(path.read_text(), filename=str(path)))
        except SyntaxError:  # pragma: no cover — arquivo inválido quebra o flake8
            continue

    violations: list[Violation] = []
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return violations

    for test_file in sorted(tests_dir.rglob("*.py")):
        if "__pycache__" in test_file.parts:
            continue
        text = test_file.read_text()
        lines = text.splitlines()
        try:
            tree = ast.parse(text, filename=str(test_file))
        except SyntaxError:
            continue
        aliases = _test_alias_map(tree)
        rel = str(test_file.relative_to(root))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for dotted_expr, arg in _targets_in_call(node):
                resolved = resolve_module(dotted_expr, _str_arg(arg), aliases, index)
                if resolved is None:
                    continue
                module, name = resolved
                if name in owned.get(module, set()):
                    continue
                if _has_escape(
                    lines,
                    getattr(node, "lineno", 0),
                    getattr(node, "end_lineno", None) or getattr(node, "lineno", 0),
                ):
                    continue
                violations.append(
                    Violation(rel, getattr(arg, "lineno", 0), module, name)
                )
    return violations


def main(root: Path | None = None, list_only: bool = False) -> int:
    root = root or ROOT
    try:
        violations = find_violations(root)
    except Exception as exc:  # pragma: no cover — erro de execução
        print(f"❌ monkeypatch-targets guard: erro ao analisar: {exc}")
        return 2

    if list_only:
        for v in violations:
            print(str(v))
        print(f"\n{len(violations)} alvo(s) órfão(s)")
        return 0

    if not violations:
        print("✅ monkeypatch-targets guard green — nenhum patch em alvo órfão")
        return 0

    print("❌ monkeypatch-targets guard FAILED — patch(es) em alvo órfão:\n")
    for v in violations:
        print(f"  {v}")
    print(
        "\nO patch NÃO intercepta o código: o nome mudou de casa e o módulo "
        "antigo só o re-exporta.\nAponte o patch para o módulo DONO "
        "(ex.: onde o símbolo é definido) ou documente a exceção com\n"
        f"`# {OK_MARKER}: <motivo>` na própria linha.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(list_only="--list" in sys.argv[1:]))
