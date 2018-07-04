from functools import partial, wraps
from uuid import getnode
from logging import getLogger
from time import sleep

from gps import EarthDistance

from wialond.connection import Connection
from wialond.position import make_position_getter
from wialond.picture import take_picture
from wialond.util.concurrency import BlockingDeque, BlockingQueue, spawn


logger = getLogger(__name__)


def make_producer(put, func, cooldown=0):
    while True:
        try:
            put(func())
        except Exception:
            logger.error("Producer failure", exc_info=1)
        sleep(cooldown)


def make_consumer(queue, func):
    for value in queue:
        try:
            func(value)
        except Exception:
            logger.error("Consumer failure", exc_info=1)


def connection_loop(conn, make_workers):
    try:
        conn.send_login(getnode()).get(timeout=60)
    except (TimeoutError, ConnectionError):
        return

    logger.info("Successful login")

    stop_workers = make_workers(conn)
    try:
        conn.wait_for_close()
    finally:
        stop_workers()


def serve(address, cooldown, **kwargs):
    logger.info("Serving {}".format(address))
    while True:
        try:
            with Connection(address) as conn:
                connection_loop(conn, **kwargs)
        except Exception:
            logger.error("Server loop failure", exc_info=1)
        sleep(cooldown)


def run(consumers, producers, gpsd, camera, server):
    ack_timeout = 30
    logger.info("Starting wialond")

    def make_position_sender(send_position):
        deadline, distance = (consumers['position'][k] for k in ('deadline', 'distance'))
        ptimestamp, plocation = float('-inf'), None

        @wraps(send_position)
        def wrapper(args):
            nonlocal plocation, ptimestamp
            timestamp, position = args
            location = position[:2]
            if timestamp - ptimestamp >= deadline or EarthDistance(location, plocation) >= distance:
                send_position(int(timestamp), position).get(ack_timeout)
                ptimestamp, plocation = timestamp, location

        return wrapper

    def make_workers(conn):
        def stop(queues, threads):
            for q in queues:
                q.interrupt()
            for t in threads:
                t.join()

        threads = [
            spawn(make_consumer, queue, func) for queue, func in (
                (keep_alives, lambda x: conn.send_keep_alive()),
                (positions, BlockingDeque.managed_handler(make_position_sender(conn.send_position))),
                (pictures, BlockingDeque.managed_handler(lambda x: conn.send_picture(int(x[0]), x[1]).get(ack_timeout))),
            )
        ]
        return partial(stop, (keep_alives, positions, pictures), threads)

    keep_alives = BlockingQueue(1)
    positions = BlockingDeque(producers['position']['size'])
    pictures = BlockingDeque(producers['picture']['size'])

    threads = [
        spawn(serve, make_workers=make_workers, **server), *(
            spawn(make_producer, *params) for params in (
                (keep_alives.put, lambda: 1, producers['keep-alive']['cooldown']),
                (positions.put, make_position_getter(gpsd['address'])),
                (
                    pictures.put, partial(take_picture, camera['path'], camera.get('transport', 'tcp')),
                    producers['picture']['cooldown'],
                ),
            )
        ),
    ]

    for t in threads:
        t.join()
