import sqlite3
from pathlib import Path
import os

LUSTRE_DATA_DIR = Path(os.getenv("LUSTRE_DATA_DIR", ".lustre"))


def _db_path() -> Path:
    LUSTRE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return LUSTRE_DATA_DIR / "checkpoints.sqlite"


def make_checkpointer():
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    return SqliteSaver(conn)


def list_thread_ids() -> list[str]:
    db = _db_path()
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(str(db), check_same_thread=False)
        try:
            cur = conn.execute(
                "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
            )
            return [row[0] for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()
    except Exception:
        return []
