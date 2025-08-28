import uuid
from pathlib import Path
import sys
main_dir = Path(sys.argv[0]).resolve().parent

def get_path(path: str | Path):
    return main_dir / path

def get_id()->uuid:
    return uuid.uuid4()