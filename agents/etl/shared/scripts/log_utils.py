#!/usr/bin/env python3
"""
Shared logging utilities for Hermes ETL Manager.
HKT (UTC+8) formatter — all log timestamps display in Hong Kong time.
No DST — HKT is always UTC+8.
"""

import logging
import datetime

class HKTFormatter(logging.Formatter):
    """Display log timestamps in HKT (UTC+8)."""
    
    def converter(self, timestamp):
        dt = datetime.datetime.utcfromtimestamp(timestamp)
        return (dt + datetime.timedelta(hours=8)).timetuple()

    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        if datefmt:
            return datetime.datetime(*ct[:6]).strftime(datefmt) + ' HKT'
        return datetime.datetime(*ct[:6]).strftime('%Y-%m-%d %H:%M:%S') + ' HKT'


def get_logger(name):
    """Get a logger with HKT timestamp formatting."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(HKTFormatter('%(asctime)s — %(levelname)s — %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
