from collections import OrderedDict
from contextlib import contextmanager
from functools import wraps
from itertools import cycle
from threading import Thread, Event
from queue import Queue as _Queue


def spawn(func, *args, **kwargs):
    t = Thread(target=func, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t


class BlockingQueue(_Queue):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__interrupted = False

    def interrupt(self):
        with self.mutex:
            self.__interrupted = True
            self.not_empty.notify()

    def __iter__(self):
        return self

    def __next__(self):
        value = self.get()
        if value is StopIteration:
            raise value
        return value

    def _qsize(self):
        return self._qsize_impl() + self.__interrupted

    def _get(self):
        if self.__interrupted:
            self.__interrupted = False
            return StopIteration
        return self._get_impl()

    _get_impl = _Queue._get
    _qsize_impl = _Queue._qsize


class BlockingDeque(BlockingQueue):
    def __init__(self, maxsize=0):
        super().__init__(-abs(maxsize))

    def _init(self, maxsize):
        self.__maxsize = abs(maxsize)
        self.__counter = cycle(range(1 << 64))
        self.__storage = OrderedDict()

    def _put(self, item):
        while len(self.__storage) >= self.__maxsize:
            self.__storage.popitem(last=False)
        self.__storage[next(self.__counter)] = item

    def _get_impl(self):
        key, value = next(iter(self.__storage.items()))
        return self._managed_result(key, value)

    def _qsize_impl(self):
        return len(self.__storage)

    @contextmanager
    def _managed_result(self, key, value):
        yield value
        with self.mutex:
            self.__storage.pop(key, None)

    @staticmethod
    def managed_handler(func):
        @wraps(func)
        def wrapper(managed_value):
            with managed_value as value:
                return func(value)
        return wrapper


class AsyncResult(Event):
    def set_result(self, result):
        self._result = result
        self.set()

    def set_error(self, error):
        if not (isinstance(error, BaseException) or (isinstance(error, type) and issubclass(error, BaseException))):
            raise TypeError
        self._error = error
        self.set()

    def get(self, timeout=None):
        self.wait(timeout)
        if hasattr(self, '_error'):
            raise self._error
        if hasattr(self, '_result'):
            return self._result
        raise AssertionError("At least one of '_result' and '_error' must be set")

    def wait(self, *args, **kwargs):
        if not super().wait(*args, **kwargs):
            raise TimeoutError
