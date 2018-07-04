from datetime import datetime, timezone
from logging import getLogger
from time import sleep

import gps


logger = getLogger(__name__)


def _produce_positions(addr):
    session = gps.gps(*addr)
    session.stream(flags=gps.WATCH_JSON)

    timestamp, position, stats, hdop = [None] * 4

    for report in session:
        if report['class'] == 'SKY':
            stats = sum(1 for x in report['satellites'] if x['used'])
            hdop = report.get('hdop')
        elif report['class'] == 'TPV':
            timestamp = datetime.strptime(
                report['time'], '%Y-%m-%dT%H:%M:%S.%fZ'
            ).replace(tzinfo=timezone.utc).timestamp()
            position = tuple(
                report[k] for k in ('lat', 'lon', 'speed', 'track', 'alt')
            )
        if all(x is not None for x in (position, stats, hdop)):
            yield (timestamp, (*position, stats, hdop))


def _safe_produce_positions(addr, error_cooldown=3):
    while True:
        try:
            for item in _produce_positions(addr):
                yield item
        except Exception:
            logger.error("Failed get position", exc_info=1)
            sleep(error_cooldown)


def make_position_getter(addr):
    return _safe_produce_positions(addr).__next__
