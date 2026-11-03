# 参与维护

这个项目负责汉化构建，不维护 REFramework 引擎本体。新增功能应与词库、汉化注入、构建或发布直接相关。

## 修改词库

`translations.txt` 使用 UTF-8，格式为 `英文原文=中文`；原文包含 `=` 时使用制表符分隔。换行、回车、制表符和反斜杠分别写为 `\n`、`\r`、`\t`、`\\`。`#` 开头的行是注释。

优先补精确原文词条。`hash_dict.txt` 为旧版兼容词库，缺少原文时无法核对哈希碰撞；不要仅凭相似界面猜测并覆盖现有词条。

## 本地检查

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m unittest discover -s tests -v
```

Python 测试不访问真实发布服务。核心翻译测试会使用 `g++` 或 `clang++` 编译并执行生成的 C++；Windows 可通过 `REF_TEST_CXX` 指定编译器。没有编译器时本地会明确跳过，持续集成禁止跳过。

需要检查实际 ImGui 行为时，将 `IMGUI_TEST_SOURCE` 指向已检出的 ImGui 源码目录；标准构建目录为 `REFramework-src/dependencies/imgui`。持续集成会获取固定提交的源码并强制执行，不依赖维护者的本地目录。

## 修改边界

- `build_chinese.py` 只保留命令行入口，职责分布见 [代码结构](docs/architecture.md)。
- 词库算法在 `templates/Translation.cpp`，修改后同时检查文本片段、特殊字符、同译名控件和原有窗口标识。
- 上游函数定位必须唯一；不匹配时停止，不打印虚假的成功信息。
- 普通构建只生成本地文件。发布行为必须显式执行，且目标归属于当前仓库。
- 原作者署名、上游许可证和既有下载记录必须保留；不要把 Fork 的统计累加到原项目。
- 新增验证应能发现具体问题，不用测试数量代替有效覆盖。
