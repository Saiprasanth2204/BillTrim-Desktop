from contextlib import contextmanager
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.logging_config import get_logger

logger = get_logger("db_transaction")


@contextmanager
def db_transaction(db: Session = None):
    if db is None:
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Transaction rolled back: {str(e)}", exc_info=True)
        raise
    finally:
        if should_close:
            db.close()


def safe_commit(db: Session, operation_name: str = "operation") -> bool:
    try:
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"{operation_name} failed: {str(e)}", exc_info=True)
        return False
