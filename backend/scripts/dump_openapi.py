"""Print the FastAPI app's OpenAPI schema as JSON on stdout.

Used by the frontend's `npm run gen:types` so types can be generated without
starting a server. core.py chdirs on import, so write to stdout, not a path.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402

json.dump(app.openapi(), sys.stdout, indent=2)
