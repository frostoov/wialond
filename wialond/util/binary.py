from itertools import count, takewhile
from struct import Struct as BaseStruct


class Struct(BaseStruct):
    def read_from(self, reader):
        return self.unpack(reader.read(self.size))

    def write_to(self, writer, *args):
        return writer.write(self.pack(*args))

    def read_one_from(self, reader):
        return self.read_from(reader)[0]

    def unpack_one(self, buf):
        return self.unpack(buf)[0]


read_uint = {
    x.size: x.read_one_from for x in map(Struct, ['!B', '!H', '!I', '!Q'])
}

pack_uint = {
    x.size: x.pack for x in map(Struct, ['!B', '!H', '!I', '!Q'])
}

unpack_uint = {
    x.size: x.unpack_one for x in map(Struct, ['!B', '!H', '!I', '!Q'])
}


def read_c_string(reader):
    return b''.join(takewhile(lambda x: x != b'\0', (reader.read(1) for _ in count())))


def read_var_with_buf(reader, n):
    buf = reader.read(n)
    if buf[0] & 1 << 7:
        buf += reader.read(n)
    val = unpack_uint[len(buf)](buf)
    if len(buf) > n:
        val = val ^ (1 << (16 * n - 1))
    return val, buf


def read_var(reader, n):
    return read_var_with_buf(reader, n)[0]


def pack_var(val, n):
    if val < (1 << (8 * n - 1)):
        return pack_uint[n](val)
    elif val < (1 << (16 * n - 1)):
        return pack_uint[2 * n](1 << (16 * n - 1) | val)
    else:
        raise ValueError
