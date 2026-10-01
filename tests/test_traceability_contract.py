"""Keep the documented test matrix linked to collected tests or explicit blockers."""

import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STRATEGY = ROOT / "docs" / "TEST_STRATEGY.md"


def _covers_markers(expressions):
    """Read only pytest.mark.covers decorators, excluding arbitrary lookalikes."""
    markers = []
    for expression in expressions:
        for node in ast.walk(expression):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr != "covers"
                or not isinstance(node.func.value, ast.Attribute)
                or node.func.value.attr != "mark"
                or not isinstance(node.func.value.value, ast.Name)
                or node.func.value.value.id != "pytest"
                or not node.args
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
            ):
                continue
            status = next(
                (
                    keyword.value.value
                    for keyword in node.keywords
                    if keyword.arg == "status"
                    and isinstance(keyword.value, ast.Constant)
                ),
                "full",
            )
            markers.append((node.args[0].value, status))
    return markers


def _declared_test_links():
    """Map markers to pytest-discoverable function/class node IDs in source."""
    links = {}
    for path in (ROOT / "tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative_path = path.relative_to(ROOT).as_posix()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                nodeid = f"{relative_path}::{node.name}"
                for requirement_id, status in _covers_markers(node.decorator_list):
                    links.setdefault(requirement_id, []).append((nodeid, status))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                class_markers = _covers_markers(node.decorator_list)
                for method in node.body:
                    if not isinstance(
                        method, ast.FunctionDef
                    ) or not method.name.startswith("test_"):
                        continue
                    nodeid = f"{relative_path}::{node.name}::{method.name}"
                    for requirement_id, status in [
                        *class_markers,
                        *_covers_markers(method.decorator_list),
                    ]:
                        links.setdefault(requirement_id, []).append((nodeid, status))

    for spec in (ROOT / "tests" / "e2e").glob("*.spec.js"):
        source = spec.read_text(encoding="utf-8")
        pattern = re.compile(
            r"test-requirement:\s*([A-Z]+-\d{3})\s+status=(full|partial)"
            r"(?:(?!test-requirement:).){0,200}\btest\s*\(",
            re.DOTALL,
        )
        for requirement_id, status in pattern.findall(source):
            links.setdefault(requirement_id, []).append(
                (f"{spec.relative_to(ROOT).as_posix()}::Playwright test", status)
            )
    return links


def _table_rows(text, heading):
    start = text.index(heading)
    section = text[start:]
    rows = []
    started = False
    for line in section.splitlines():
        if line.startswith("|"):
            rows.append(line)
            started = True
        elif started:
            break
    return rows


def test_every_matrix_requirement_has_test_link_or_documented_exception(pytestconfig):
    text = STRATEGY.read_text(encoding="utf-8")
    plan_rows = _table_rows(text, "| ID | Tipo |")
    plan_ids = [
        cells[1].strip()
        for line in plan_rows[2:]
        if len(cells := line.split("|")) > 2
        and re.fullmatch(
            r"(?:MF|API|OPS|TEL|TIME|NUM|SEC|CMD|AUD|PER|UI|LOAD)-\d{3}",
            cells[1].strip(),
        )
    ]
    requirement_ids = {*plan_ids}
    assert len(plan_ids) == len(
        requirement_ids
    ), "Plan table contains duplicate requirement IDs"

    status_rows = _table_rows(text, "| ID | Estado | Evidência / Issue |")
    statuses = {
        cells[1].strip(): cells[2].strip().split()[0].strip("*`")
        for line in status_rows[2:]
        if len(cells := line.split("|")) > 3 and cells[1].strip() in requirement_ids
    }
    status_ids = [
        cells[1].strip()
        for line in status_rows[2:]
        if len(cells := line.split("|")) > 3 and cells[1].strip() in requirement_ids
    ]
    assert len(status_ids) == len(
        set(status_ids)
    ), "Coverage map contains duplicate requirement IDs"
    assert set(statuses.values()) <= {
        "implementado",
        "parcial",
        "lacuna",
        "bloqueado",
    }, "Coverage map contains an unsupported state"

    exception_header = "| ID | Categoria | Justificativa | Acompanhamento |"
    exception_rows = _table_rows(text, exception_header)
    exception_ids = [
        cells[1].strip()
        for line in exception_rows[2:]
        if len(cells := line.split("|")) > 4
        and re.fullmatch(
            r"(?:MF|API|OPS|TEL|TIME|NUM|SEC|CMD|AUD|PER|UI|LOAD)-\d{3}",
            cells[1].strip(),
        )
    ]
    exceptions = {
        cells[1].strip(): (cells[2].strip(), cells[3].strip(), cells[4].strip())
        for line in exception_rows[2:]
        if len(cells := line.split("|")) > 4 and cells[1].strip() in requirement_ids
    }
    assert len(exception_ids) == len(
        set(exception_ids)
    ), "Exception table contains duplicate IDs"
    assert (
        set(exception_ids) <= requirement_ids
    ), "Exception table contains an unknown matrix ID"

    declared_links = _declared_test_links()
    collected_links = getattr(pytestconfig, "_requirement_test_links", {})
    missing = requirement_ids - set(declared_links) - set(exceptions)
    assert (
        not missing
    ), f"Matrix IDs without test links or explicit exceptions: {sorted(missing)}"
    assert not (
        set(declared_links) & set(exceptions)
    ), "An ID cannot be covered and excepted simultaneously"
    assert requirement_ids == set(
        statuses
    ), "Coverage map must contain every planned ID exactly once"
    assert all(
        statuses[requirement_id] == category
        for requirement_id, (category, _, _) in exceptions.items()
    ), "Exception categories must match the coverage state"

    tests_directory_requested = any(
        str(argument).rstrip("/").endswith("/tests")
        or str(argument).rstrip("/") == "tests"
        for argument in pytestconfig.invocation_params.args
    )
    # Collection selectors intentionally omit items from session.items. A
    # focused run such as ``pytest tests/ -k traceability`` must validate the
    # source declarations without pretending that pytest collected the whole
    # suite. The complete-collection assertion applies only when no selector
    # can filter the tests directory.
    full_suite_requested = tests_directory_requested and not any(
        (
            pytestconfig.getoption("keyword", default=""),
            pytestconfig.getoption("markexpr", default=""),
            pytestconfig.getoption("ignore", default=[]),
            pytestconfig.getoption("ignore_glob", default=[]),
            pytestconfig.getoption("deselect", default=[]),
        )
    )

    for requirement_id, targets in declared_links.items():
        assert (
            requirement_id in requirement_ids
        ), f"Unknown test marker: {requirement_id}"
        expected = {"implementado": "full", "parcial": "partial"}.get(
            statuses[requirement_id], statuses[requirement_id]
        )
        actual = {status for _, status in targets}
        assert actual == {
            expected
        }, f"{requirement_id}: map says {statuses[requirement_id]!r}, test markers say {sorted(actual)!r}"
        collected = {
            nodeid: status for nodeid, status in collected_links.get(requirement_id, [])
        }
        for nodeid, status in targets:
            matching_collected = {
                collected_nodeid: collected_status
                for collected_nodeid, collected_status in collected.items()
                if collected_nodeid.split("[", 1)[0] == nodeid
            }
            if matching_collected:
                assert set(matching_collected.values()) == {status}
            elif full_suite_requested:
                assert (
                    False
                ), f"{requirement_id}: pytest did not collect declared test {nodeid}"

    for requirement_id, (_, reason, follow_up) in exceptions.items():
        assert (
            reason.strip() and "TBD" not in reason and re.search(r"#\d+", follow_up)
        ), f"{requirement_id} needs a reason and linked Issue/PR"
