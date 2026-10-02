"""One GUI or installation transaction per installation root."""
from bootstrap.platform import Mutex
from .paths import APP_DIR


class InstanceGuard(Mutex):
    def __init__(self):
        super().__init__(APP_DIR, timeout=5000)
