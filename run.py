"""无限画布 — 启动入口"""

import sys
import os

# 确保 server 包可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.main import main

if __name__ == "__main__":
    main()
