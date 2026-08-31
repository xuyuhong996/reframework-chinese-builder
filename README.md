# REFramework Chinese Builder

这是一个为 REFramework 注入中文文本并自动打包发布的构建仓库。

## 使用范围说明

当前发布的 DLL **仅在《怪物猎人：荒野》** 中由作者实际使用过。

REFramework 也会被其他游戏使用，但作者没有在其他游戏中安装或验证过本项目生成的 DLL。因此，**不保证它适用于任何其他游戏**；请不要把它当作其他游戏的通用汉化 DLL 使用。

## 获取成品

请前往仓库的 [Releases](../../releases) 页面下载最新 ZIP。每个 Release 都会保留历史版本，并附带同名的 `SHA256` 校验文件。

## 自动构建

GitHub Actions 每天检查一次；距离上次成功发布满 72 小时时，使用 Windows Server 2022 上的 Visual Studio 2022 构建环境生成新的 ZIP 并创建 Release。

## 打赏支持

如果这个项目对你有帮助，欢迎通过微信打赏支持维护。二维码将在收到图片后添加到这里。

## 本地手动构建

```powershell
python build_chinese.py
```
