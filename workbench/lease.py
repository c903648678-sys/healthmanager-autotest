"""Process lease prevents different ports from sharing one writable workspace."""
import os
from pathlib import Path


class WorkspaceLease:
    def __init__(self, folder):
        path = Path(folder) / '.writer.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+b')
        self.file.seek(0)
        self.file.write(b'0')
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise OSError('此工作区已由其他工作台进程打开，请使用原入口或先关闭原进程。')

    def close(self):
        if not self.file.closed:
            self.file.close()
