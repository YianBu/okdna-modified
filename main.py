import os
import sys

# 新版 ok UI（来自 ok-ww 的 shell/kit）随项目放在 vendor/ok，优先于环境里的旧版。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor'))

import ok
from src.config import config

if __name__ == '__main__':
    config = config
    ok = ok.OK(config)
    ok.start()
