"""Write the OpenAPI schema to packages/api/openapi.json (input for the typed web/mobile client)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402

out = Path(__file__).resolve().parents[2] / "packages" / "api" / "openapi.json"
out.write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
print(f"wrote {out}")
