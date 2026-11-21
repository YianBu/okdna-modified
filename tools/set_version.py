"""Write the release tag into src/config.py (CI uses this on tag builds)."""
import io
import re
import sys

path = "src/config.py"
if len(sys.argv) < 2 or not sys.argv[1].strip():
    raise SystemExit("usage: python tools/set_version.py <tag>")
version = sys.argv[1].strip()

with io.open(path, encoding="utf-8") as f:
    content = f.read()

new_content, count = re.subn(r'^version = ".*"$', 'version = "%s"' % version, content, count=1, flags=re.M)
if count != 1:
    raise SystemExit("version line not found in " + path)

with io.open(path, "w", encoding="utf-8", newline="") as f:
    f.write(new_content)

print("version =", version)
