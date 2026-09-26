"""Print parser event counts over all local session files.

Usage: ``python -m vibecheck.ingest.survey``
"""

import json

from vibecheck.config import load_config
from vibecheck.ingest.discover import discover_files
from vibecheck.ingest.parser import summarize

if __name__ == "__main__":
    cfg = load_config()
    print(json.dumps(summarize(f.path for f in discover_files(cfg.claude_projects_dir)), indent=2))
