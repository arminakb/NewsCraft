from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from newscraft.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
