"""Start the chat mode: python scripts/chat.py, then type orders in the browser page it opens.

The chat mode itself is in src/ssm3/chat.py and src/ssm3/chat_server.py. This file only
puts src on the path, so it runs from a fresh clone without installing the package.
Every order uses the Groq free-tier limit. Stop it with Ctrl+C.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ssm3.chat_server import main  # noqa: E402

if __name__ == "__main__":
    main()
