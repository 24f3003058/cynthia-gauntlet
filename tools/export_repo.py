"""Export OUR files (whitelist only) into repo/ for the public GitHub repository.

PYTHONPATH=. python tools/export_repo.py [--dest repo]

Never exports the organisers' simulator (engine/, cynthia_data/, variants/, config/, docs/, ui/, ...) and never
anything under variants_private/. Re-run before every commit so repo/ matches submission/ exactly; the script
verifies team.json / policy.py are byte-identical to submission/ and that no forbidden path was copied.
"""
import argparse
import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Our work. Directories are copied recursively (minus EXCLUDE); files individually.
WHITELIST = [
    "submission/team.json", "submission/policy.py", "submission/README.md",
    "harness", "policy_src", "policy_build", "results",
    "EXPERIMENT_LOG.md", "PROGRESS.md",
    "tools/build_policy.py", "tools/compare.py", "tools/diff_bundle.py", "tools/export_repo.py",
    "tools/make_wide.py", "tools/movesets.py", "tools/phase1_eval.py", "tools/quick_eval.py",
    "tools/sweep.py", "tools/team_search.py", "tools/turn_timing.py", "tools/verify_fastcache.py",
    "tools/phase1_baseline_site_default.txt", "tools/phase1_examples.txt", "tools/phase1_run1000team.txt",
]
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", "cynthia_data_v1_backup"}   # backup = organisers' data
FORBIDDEN = ("variants_private", "engine/", "cynthia_data/", "variants/", "config/", "docs/", "ui/")

GITIGNORE = "__pycache__/\n*.py[cod]\n.pytest_cache/\n"
GITATTRIBUTES = "* -text\n"   # store bytes exactly: the GitHub copies must equal the uploaded files


def sha1(p):
    return hashlib.sha1(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="repo")
    dest = (ROOT / ap.parse_args().dest).resolve()
    dest.mkdir(exist_ok=True)
    # wipe previous export (keep .git)
    for p in dest.iterdir():
        if p.name == ".git":
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    copied = []
    for rel in WHITELIST:
        src = ROOT / rel
        files = [src] if src.is_file() else [f for f in src.rglob("*") if f.is_file()]
        for f in files:
            r = f.relative_to(ROOT)
            if EXCLUDE_PARTS & set(r.parts):
                continue
            out = dest / r
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, out)
            copied.append(r.as_posix())
    shutil.copy2(ROOT / "submission" / "README.md", dest / "README.md")
    copied.append("README.md")
    (dest / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (dest / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")

    bad = [c for c in copied if "variants_private" in c or c.startswith(FORBIDDEN)]
    assert not bad, f"forbidden paths exported: {bad}"
    home = Path.home().name.lower()            # never publish the local account name / home path
    leaks = [c for c in copied if home in (dest / c).read_bytes().decode("utf-8", "ignore").lower()]
    assert not leaks, f"files mention the local home folder '{home}': {leaks}"
    for name in ("team.json", "policy.py"):
        a, b = ROOT / "submission" / name, dest / "submission" / name
        assert sha1(a) == sha1(b), f"{name} differs from submission/"
        print(f"{name}: sha1 {sha1(b)} (matches submission/)")
    size = sum((dest / c).stat().st_size for c in copied)
    print(f"exported {len(copied)} files, {size / 1024:.0f} KB -> {dest}")


if __name__ == "__main__":
    main()
