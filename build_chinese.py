#!/usr/bin/env python3
"""REFramework 汉化构建入口，具体职责由 scripts 中的模块承担。"""

import sys

from scripts.build_pipeline import main

if __name__ == "__main__":
    sys.exit(main())
