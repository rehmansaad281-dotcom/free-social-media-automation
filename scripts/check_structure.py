"""Secret-free CI checks, run from the repository root."""
import ast
from pathlib import Path
import re
import subprocess
import tempfile

for path in Path("backend").rglob("*.py"):
    ast.parse(path.read_text(), filename=str(path))
html = Path("frontend/index.html").read_text()
ids = re.findall(r'\bid="([^"]+)"', html)
assert len(ids) == len(set(ids)), "Duplicate frontend IDs"
script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
for referenced in re.findall(r'\$\("([^"]+)"\)', script):
    assert referenced in ids, f"Unknown frontend ID: {referenced}"
with tempfile.TemporaryDirectory() as temp:
    js = Path(temp) / "frontend.js"
    js.write_text(script)
    subprocess.run(["node", "--check", str(js)], check=True)
for path in ("Dockerfile", "docker-compose.yml", ".env.example", "backend/requirements.txt", "frontend/index.html"):
    assert Path(path).is_file(), path
print("Python AST, frontend IDs, JavaScript syntax, and deployment structure OK")
