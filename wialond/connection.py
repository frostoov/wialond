from functools import wraps
from itertools import chain, cycle
from logging import getLogger
from socket import create_connection
import struct
from threading import Semaphore
from uuid import uuid4

from wialond.util import binary
from wialond.util.crc16 import calc_crc16
from wialond.util.concurrency import AsyncResult, Event, spawn

logger = getLogger(__name__)


class ConnectionClosedError(ConnectionError):
    pass


def _io_operation(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except ConnectionError:
            self.close()
            raise
    return wrapper


class Connection:

    def __init__(self, addr):
        self._socket = create_connection(addr)
        self._reader = self._socket.makefile(mode='rb')
        self._acks = {}
        self._message_counter = cycle(range(1 << 16))
        self._closed = Event()
        self._write_mutex = Semaphore()
        self._listen_thread = spawn(self._listen)

    @property
    def active(self):
        return not self._closed.is_set()

    def wait_for_close(self, *args, **kwargs):
        return self._closed.wait(*args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        self._listen_thread.join()

    def send_login(self, mac):
        mac = '{mac}\0'.format(mac=mac).encode()
        payload = struct.pack('!BB{}s'.format(len(mac)), 1, 64, mac)
        return self._send_message(0, binary.pack_var(len(payload), 2) + payload)

    def send_picture(self, timestamp, data):
        index = binary.pack_var(0, 1)
        return self._send_data(
            timestamp,
            b''.join([
                binary.pack_var(3, 1),
                index,
                binary.pack_var(len(data), 2),
                index,
                '{}\0'.format(uuid4().hex).encode(),
                data,
            ])
        )

    def send_position(self, timestamp, position):
        lat, lon, speed, course, height, stats, hdop = position
        return self._send_data(
            timestamp,
            struct.pack(
                '!BIIHHHBH',
                1, int(lat * 1000000), int(lon * 1000000),
                int(speed), int(course),
                int(height), stats, int(hdop)
            ),
        )

    def send_keep_alive(self):
        return self._send_message(2)

    def _send_data(self, timestamp, data):
        payload = struct.pack('!IB{}s'.format(len(data)), timestamp, 1, data)
        return self._send_message(1, binary.pack_var(len(payload), 2) + payload)

    def _send_message(self, msg_type, payload=b''):
        seq = next(self._message_counter)
        async_result = AsyncResult()
        self._acks[seq] = async_result
        body = b''.join([
            binary.pack_uint[2](0x2424),
            binary.pack_var(msg_type, 1),
            binary.pack_uint[2](seq),
            payload,
        ])
        if msg_type != 2:
            body += binary.pack_uint[2](calc_crc16(body))
        self.write(body)
        return async_result

    @_io_operation
    def read(self, size=-1):
        data = self._reader.read(size)
        if size > 0 and not data:
            raise ConnectionClosedError
        return data

    @_io_operation
    def readline(self, size=-1):
        data = self._reader.readline(size)
        if size > 0 and not data:
            raise ConnectionClosedError
        return data

    @_io_operation
    def write(self, b):
        with self._write_mutex:
            return self._socket.sendall(b)

    def close(self):
        self._closed.set()
        self._socket.close()
        self._reader.close()
        while self._acks:
            _, async_result = self._acks.popitem()
            async_result.set_error(ConnectionClosedError)

    def _listen(self):
        try:
            while self.active:
                self._handle_message()
        except ConnectionClosedError:
            pass
        except Exception:
            logger.error("Connection listen failure", exc_info=1)
            self.close()

    def _handle_message(self):
        header_buf = self.read(3)
        head, code = struct.unpack('!HB', header_buf)
        assert head == 0x4040, str([head, code])
        if code == 255:
            self._handle_command(header_buf)
        elif 0 <= code <= 4:
            self._handle_ack(code)
        else:
            raise ValueError("Invalid code value: {}".format(code))

    def _handle_ack(self, code):
        (seq,) = struct.unpack('!H', self.read(2))
        async_result = self._acks.pop(seq, None)
        if async_result is None:
            return
        if code == 0:
            async_result.set_result(True)
        else:
            async_result.set_error(Exception(code))

    def _handle_command(self, header_buf):
        size, size_buf = binary.read_var_with_buf(self, 2)
        timestamp_buf = self.read(4)
        binary.unpack_uint[4](timestamp_buf)  # ignored timestamp
        cmd_type, cmd_type_buf = binary.read_var_with_buf(self, 1)
        assert cmd_type == 0
        data = self.readline()
        crc16 = binary.read_uint[2](self)
        calced_crc16 = calc_crc16(
            chain(header_buf, size_buf, timestamp_buf, cmd_type_buf, data)
        )
        if crc16 != calced_crc16:
            raise ValueError("Invalid crc16: {} != {}".format(crc16, calced_crc16))
