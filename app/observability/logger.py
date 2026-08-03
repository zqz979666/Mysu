"""
日志工具
"""

import logging
import sys

logger = logging.getLogger("mysu")
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
)
logger.addHandler(handler)
