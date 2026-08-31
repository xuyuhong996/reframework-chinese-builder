# REFramework Chinese Builder

这是一个为 REFramework 注入中文文本并自动打包发布的构建仓库。

## 原项目与作者

REFramework 的原作者项目为 [praydog/REFramework](https://github.com/praydog/REFramework)。本仓库在每次构建时拉取其 `master` 分支源码，并在此基础上注入中文文本后生成发布包。

本仓库是独立的汉化构建与发布项目，**不是 REFramework 原作者的官方仓库，也不代表原作者提供支持或兼容性保证**。REFramework 本体的源码、更新与技术问题请以原作者仓库为准。

## 使用范围说明

当前发布的 DLL **仅在《怪物猎人：荒野》** 中由作者实际使用过。

REFramework 也会被其他游戏使用，但作者没有在其他游戏中安装或验证过本项目生成的 DLL。因此，**不保证它适用于任何其他游戏**；请不要把它当作其他游戏的通用汉化 DLL 使用。

## 获取成品

请前往仓库的 [Releases](../../releases) 页面下载最新 ZIP。每个 Release 都会保留历史版本，并附带同名的 `SHA256` 校验文件。

## 自动构建

GitHub Actions 每 15 分钟检查一次 [praydog/REFramework](https://github.com/praydog/REFramework) 的 `master` 分支。仅当检测到上游提交变化时，才使用 Windows Server 2022 上的 Visual Studio 2022 构建环境拉取代码、注入汉化并创建新的 ZIP Release；没有新提交时不会打包或发布。

## 打赏支持

如果这个项目对你有帮助，欢迎通过微信打赏支持维护。

<img src="assets/wechat-reward-qr.jpg" alt="微信收款二维码" width="320">

## 本地手动构建

```powershell
python build_chinese.py
```
