import logging

from newscraft.core.config import settings


def configure_logging():
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
