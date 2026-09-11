"""
test_monkeypatch_targets_guard.py — self-test do guard de alvo de patch órfão.

O guard (scripts/check-monkeypatch-targets.py) falha quando um teste patcheia um
nome que o módulo alvo não possui: o módulo só o re-exporta, o código real o
resolve nos globals do dono, e o patch vira no-op silencioso (o teste passa com
dados reais/vazios). Foi a armadilha do PR B3 (#502).

Roda de duas formas (padrão dos guards do repo):
    python tests/test_monkeypatch_targets_guard.py   # standalone (exit code)
    pytest tests/test_monkeypatch_targets_guard.py   # suíte completa

Testes:
1. Guard verde no repositório real.
2. Re-export patcheado → DETECTADO (o caso #502).
3. Patch no módulo DONO → permitido.
4. Nome importado E usado pelo módulo → permitido (o caso `app._build_snapshot`).
5. Forma string `patch("pkg.mod.nome")` → DETECTADA.
6. Escape hatch `# orphan-patch-ok: motivo` → permitido.
7. Módulo não first-party (requests) → ignorado.
"""

import contextlib
import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# O guard tem hífen no nome (padrão scripts/) — carrega via importlib.
_guard_path = ROOT / "scripts" / "check-monkeypatch-targets.py"
_spec = importlib.util.spec_from_file_location("check_monkeypatch_targets", _guard_path)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _fixture_tree(tmp_path: Path, test_src: str) -> Path:
    """Árvore sintética: `facade` só re-exporta, `caller` importa E usa."""
    (tmp_path / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "services" / "__init__.py").write_text("")
    (tmp_path / "services" / "owner.py").write_text(
        "def _fetch(url):\n    return {'from': 'owner', 'url': url}\n"
    )
    # Re-export puro: importa e nunca usa no corpo → NÃO é dono.
    (tmp_path / "services" / "facade.py").write_text(
        "from services.owner import _fetch  # noqa: F401\n"
    )
    # Importa E usa → É dono (o lookup de global acontece no dict deste módulo).
    (tmp_path / "services" / "caller.py").write_text(
        "from services.owner import _fetch\n\n\n"
        "def go(url):\n    return _fetch(url)\n"
    )
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_targets.py").write_text(test_src)
    return tmp_path


def _violations(tmp_path: Path, test_src: str):
    return guard.find_violations(_fixture_tree(tmp_path, test_src))


# ── 1. Repositório real ────────────────────────────────────────────────────


def test_guard_is_green_on_the_real_repository():
    assert guard.find_violations(ROOT) == []


# ── 2. O caso #502: re-export patcheado ────────────────────────────────────


def test_reexport_patch_is_detected(tmp_path):
    src = (
        "import services.facade as facade\n"
        "import pytest\n\n\n"
        "def test_x(monkeypatch):\n"
        '    monkeypatch.setattr(facade, "_fetch", lambda url: {})\n'
        "    assert facade._fetch('u') == {}\n"
    )
    found = _violations(tmp_path, src)
    assert [(v.module, v.name) for v in found] == [("services.facade", "_fetch")]


def test_guard_main_returns_1_on_orphan_target(tmp_path):
    src = (
        "import services.facade as facade\n\n\n"
        "def test_x(monkeypatch):\n"
        '    monkeypatch.setattr(facade, "_fetch", lambda url: {})\n'
    )
    tree = _fixture_tree(tmp_path, src)
    # silencia a saída do guard (ele imprime o relatório de falha)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = guard.main(root=tree)
    assert code == 1
    assert "services.facade._fetch" in buf.getvalue()


# ── 3. Patch no dono → permitido ───────────────────────────────────────────


def test_patching_the_owner_is_allowed(tmp_path):
    src = (
        "import services.owner as owner\n\n\n"
        "def test_x(monkeypatch):\n"
        '    monkeypatch.setattr(owner, "_fetch", lambda url: {})\n'
    )
    assert _violations(tmp_path, src) == []


# ── 4. Importado E usado → o módulo é dono ─────────────────────────────────


def test_module_that_uses_the_imported_name_is_an_owner(tmp_path):
    """`caller` importa `_fetch` e chama no corpo → patch nele intercepta."""
    src = (
        "import services.caller as caller\n\n\n"
        "def test_x(monkeypatch):\n"
        '    monkeypatch.setattr(caller, "_fetch", lambda url: {})\n'
    )
    assert _violations(tmp_path, src) == []


# ── 5. Forma string ────────────────────────────────────────────────────────


def test_string_form_patch_is_detected(tmp_path):
    src = (
        "from unittest.mock import patch\n\n\n"
        "def test_x():\n"
        '    with patch("services.facade._fetch", return_value={}):\n'
        "        pass\n"
    )
    found = _violations(tmp_path, src)
    assert [(v.module, v.name) for v in found] == [("services.facade", "_fetch")]


def test_string_form_on_the_owner_is_allowed(tmp_path):
    src = (
        "from unittest.mock import patch\n\n\n"
        "def test_x():\n"
        '    with patch("services.owner._fetch", return_value={}):\n'
        "        pass\n"
    )
    assert _violations(tmp_path, src) == []


# ── 6. Escape hatch documentado ────────────────────────────────────────────


def test_escape_marker_allows_a_documented_exception(tmp_path):
    src = (
        "import services.facade as facade\n\n\n"
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(\n"
        "        facade,\n"
        '        "_fetch",\n'
        "        lambda url: {},  # orphan-patch-ok: documentado\n"
        "    )\n"
    )
    assert _violations(tmp_path, src) == []


# ── 7. Não-first-party passa batido ────────────────────────────────────────


def test_third_party_module_is_ignored(tmp_path):
    src = (
        "import requests\n\n\n"
        "def test_x(monkeypatch):\n"
        '    monkeypatch.setattr(requests, "get", lambda *a, **k: None)\n'
    )
    assert _violations(tmp_path, src) == []


def test_unknown_alias_is_ignored(tmp_path):
    """Alvo que o guard não sabe resolver → fail-open, nunca falso positivo."""
    src = (
        "def test_x(monkeypatch):\n"
        "    thing = object()\n"
        '    monkeypatch.setattr(thing, "attr", 1)\n'
    )
    assert _violations(tmp_path, src) == []


def _run_all() -> int:
    """Standalone runner (exit code 0/1) — padrão dos self-tests dos guards."""
    import tempfile

    def with_tmp(fn):
        def wrapper():
            with tempfile.TemporaryDirectory() as td:
                fn(Path(td))

        return wrapper

    cases = [
        ("guard verde no repositório", test_guard_is_green_on_the_real_repository),
        ("detecta patch em re-export", with_tmp(test_reexport_patch_is_detected)),
        (
            "main()=1 no alvo órfão",
            with_tmp(test_guard_main_returns_1_on_orphan_target),
        ),
        ("permite patch no dono", with_tmp(test_patching_the_owner_is_allowed)),
        (
            "módulo que usa o import é dono",
            with_tmp(test_module_that_uses_the_imported_name_is_an_owner),
        ),
        ("detecta forma string", with_tmp(test_string_form_patch_is_detected)),
        (
            "permite string no dono",
            with_tmp(test_string_form_on_the_owner_is_allowed),
        ),
        (
            "respeita o escape hatch",
            with_tmp(test_escape_marker_allows_a_documented_exception),
        ),
        ("ignora third-party", with_tmp(test_third_party_module_is_ignored)),
        ("ignora alvo não resolvido", with_tmp(test_unknown_alias_is_ignored)),
    ]

    fails = 0
    print("monkeypatch-targets guard self-test")
    for name, fn in cases:
        try:
            fn()
            print(f"  ✅ {name}")
        except AssertionError as exc:
            print(f"  ❌ {name}: {exc}")
            fails += 1
    print()
    if fails:
        print(f"❌ self-test FAILED — {fails} teste(s) vermelho(s)")
        return 1
    print("✅ self-test green")
    return 0


if __name__ == "__main__":
    sys.exit(_run_all())
