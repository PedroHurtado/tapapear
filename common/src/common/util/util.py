from uuid import UUID, uuid4
from pathlib import Path
from datetime import datetime, timezone
from typing import TypeAlias
from uuid import UUID
import sys

ID :TypeAlias = UUID

main_dir = Path(sys.argv[0]).resolve().parent

def get_path(path: str | Path):
    return main_dir / path

def get_id()->UUID:
    return uuid4()

def get_now()->datetime:
    return datetime.now(timezone.utc)

