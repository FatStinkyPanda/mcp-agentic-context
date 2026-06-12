"""
Write-discipline guard: truncating writes can never regress into the store.
============================================================================
Every shared record write must go through atomic_write_json (temp +
os.replace) or an O_EXCL create — a bare open('w')/write_text() lets readers
observe partial JSON. This test greps the three store-writing modules and
fails on any unannotated truncating write. Intentional exceptions (the atomic
helper's own temp write, corrupt-fixture writes in selftest) carry an
inline `# write-ok` marker.
"""

from pathlib import Path
import re

SCANNED = ["agent_collab.py", "agent_comms.py", "project_state.py"]
TRUNCATING = [
    re.compile(r"\.write_text\("),
    re.compile(r"""open\([^)]*,\s*["']w b?["']"""),
    re.compile(r"""open\([^)]*,\s*["']wb?["']"""),
]


def test_no_unannotated_truncating_writes():
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    offenders = []
    for name in SCANNED:
        for lineno, line in enumerate(
                (scripts / name).read_text(encoding="utf-8").splitlines(), 1):
            if "write-ok" in line:
                continue
            if any(rx.search(line) for rx in TRUNCATING):
                offenders.append(f"{name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "truncating write outside atomic_write_json (readers can see partial "
        "JSON). Use atomic_write_json/O_EXCL, or annotate an intentional "
        "fixture with '# write-ok':\n" + "\n".join(offenders))
