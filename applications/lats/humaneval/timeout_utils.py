"""
Timeout wrapper for test execution (no dependency on LATS repo).
"""
from threading import Thread


class _PropagatingThread(Thread):
    def run(self):
        self.exc = None
        try:
            self.ret = self._target(*self._args, **self._kwargs)
        except BaseException as e:
            self.exc = e

    def join(self, timeout=None):
        super().join(timeout)
        if self.exc:
            raise self.exc
        return self.ret


def function_with_timeout(func, args, timeout):
    r = []
    def w():
        r.append(func(*args))
    t = _PropagatingThread(target=w)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError()
    return r[0]
