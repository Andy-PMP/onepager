"""Create samconfig.toml from the example with a fresh random IP-hash salt.

    .\\.venv\\Scripts\\python scripts\\make_samconfig.py

Refuses to overwrite an existing samconfig.toml, because replacing the salt resets every
visitor's daily count.
"""

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / "samconfig.toml"

if target.exists():
    sys.exit("samconfig.toml already exists; leaving it alone.")
text = (ROOT / "samconfig.example.toml").read_text(encoding="utf-8")
text = text.replace("REPLACE_WITH_64_HEX_CHARS", secrets.token_hex(32))
text = re.sub(r"(?m)^#.*\n", "", text)
target.write_text(text, encoding="utf-8")
print("Created samconfig.toml with a new salt.")
