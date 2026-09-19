"""Second patch pass: replace remaining _east_facing_plane calls (CRLF-safe)."""
from pathlib import Path

p = Path("backend/tests/unit/agriculture/test_terrain.py")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

out = []
skipping = False
for line in lines:
    stripped = line.rstrip("\r\n")
    # Replace call sites.
    if "_east_facing_plane(monkeypatch, dataset_id=" in stripped:
        stripped = stripped.replace(
            "_east_facing_plane(monkeypatch, dataset_id=SRTM)",
            "_install_dem(monkeypatch)",
        ).replace(
            "_east_facing_plane(monkeypatch, dataset_id=NASADEM)",
            "_install_dem(monkeypatch)",
        )
    elif "_east_facing_plane(monkeypatch)" in stripped:
        stripped = stripped.replace(
            "_east_facing_plane(monkeypatch)", "_install_dem(monkeypatch)"
        )
    # Remove the helper definition block: from its 'def' line up to the
    # line before the next top-level 'def' or section comment.
    if stripped.startswith("def _east_facing_plane("):
        skipping = True
        continue
    if skipping:
        if stripped.startswith("def ") or stripped.startswith("# ---"):
            skipping = False
            out.append(line if line.endswith("\n") else line + "\n")
            continue
        continue
    eol = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
    out.append(stripped + eol)

text = "".join(out)
assert "_east_facing_plane" not in text, "helper still referenced"
p.write_text(text, encoding="utf-8", newline="")
print("done")
