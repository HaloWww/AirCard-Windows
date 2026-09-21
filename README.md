# AirCard for Windows

一个面向 Windows 的 Apple Wallet 卡面管理工具。它可以替换 Wallet / Apple Pay
卡面，并在第一次修改前自动备份原始卡面，之后可一键恢复并校验。

本项目基于 [Mak5er/AirCard](https://github.com/Mak5er/AirCard) 的 AirLift 思路和
[alrrstd/AirCard-Windows](https://github.com/alrrstd/AirCard-Windows) 的 Windows
移植继续开发。

> [!WARNING]
> AirCard 使用未公开的 Apple 设备同步行为，iOS 更新可能随时使其失效。修改前请
> 备份 iPhone。程序不会在原始卡面备份失败时继续写入，但这仍属于高风险操作。

## 主要功能

- 简洁的三步式 Windows GUI：连接 iPhone、选择卡片、应用卡面
- 支持 PNG、JPG 和 WebP，自动裁切为 1536 × 969
- 同时生成 Wallet 所需的 `@3x`、`@2x` 和 PDF 卡面资源
- 可选“全图模式”，隐藏发卡行和联名 Logo
- 第一次修改前自动读取并保存原始卡面；备份失败则停止修改
- 一键恢复原始卡面，并逐文件重新读取、校验内容
- 同时刷新 `.cache` 与 `.pkcache`，兼顾 Wallet 和双击侧边键界面
- 自动发现 Apple Mobile Device Support 和已信任的 USB iPhone
- Wallet 卡片扫描、手动添加、重命名与删除本地记录
- 备用命令行界面同样支持应用和恢复

## 系统要求

- Windows 10 或 Windows 11，64 位
- Apple 官方 64 位桌面版 iTunes，且已安装 Apple Mobile Device Support
- 使用源码启动时需要 64 位 Python 3.12
- USB 数据线；iPhone 必须解锁并信任此电脑

Microsoft Store 版 iTunes 有时不会提供程序需要的 DLL。若界面显示 Apple Mobile
Device Support 未就绪，请改用 Apple 官网提供的桌面安装包。

## 快速开始

### 使用源码

```powershell
git clone https://github.com/HaloWww/AirCard-Windows.git
cd AirCard-Windows
```

双击 `AirCard.vbs` 静默启动，或双击 `run_aircard.bat` 查看首次安装过程。启动器会
创建隔离环境并安装依赖。命令行模式可运行：

```powershell
run_aircard.bat --cli
```

### 使用 GUI

1. 通过 USB 连接 iPhone，解锁并选择“信任此电脑”。
2. 在“Connect iPhone”中确认设备已连接。
3. 点击“Scan Wallet”，按提示在 iPhone 上打开并点选目标卡；也可以手动添加卡片哈希。
4. 选择卡面图片，确认预览，需要时开启“Full-art mode”。
5. 点击“Apply card skin”。第一次修改会先备份原始卡面；备份失败时不会写入。
6. 强制关闭 iPhone 上的 Wallet，再重新打开查看效果。

## 恢复原始卡面

连接备份时使用的同一台 iPhone，并选择同一张卡。“Restore original”按钮会在存在
有效备份时自动启用。点击后，AirCard 会：

1. 校验本地备份的 SHA-256 和文件大小；
2. 写回原始卡面及 Logo，并移除修改时新增、原本不存在的资源；
3. 刷新两类 Wallet 缓存；
4. 从设备重新读取已恢复资源并逐字节校验。

备份保存在：

```text
%LOCALAPPDATA%\AirCard\backups
```

每份备份按设备和卡片隔离，并采用原子写入；已有备份不会被后续修改覆盖。不要在需要
恢复前删除该目录。

## 构建 Windows EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

输出位于 `dist\AirCard.exe`。可执行文件不捆绑 Apple DLL，用户仍需安装官方 Apple
Mobile Device Support。GitHub Actions 也提供手动触发的 `Windows build` 工作流。

## 测试与兼容性

- 单元测试覆盖：备份完整性、防篡改、卡面/PDF 生成、批量写入编排、双缓存刷新、
  全图 Logo 与恢复路径的关键逻辑。
- Windows GUI 已完成实际启动检查；设备发现已在真实 USB iPhone 上通过。
- 当前开发环境没有对用户的 Wallet 卡片执行写入，因此本版本的完整写入/恢复流程仍需
  在自有测试设备上谨慎验证。
- AirLift 是否可用取决于具体 iOS 版本和 build；“能连接”不等于“该版本一定可写”。

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 隐私与安全

AirCard 不需要 Apple ID、银行卡号或验证码。它会在本机保存设备标识、Wallet 卡片哈希
和原始卡面资源，用于后续恢复。项目不会主动上传这些数据。

## 第三方组件与许可

项目代码沿用 MIT License。运行依赖包括 Flet、Pillow、Rich 和
`pymobiledevice3`；其中 `pymobiledevice3` 采用 GPL-3.0 许可证。发布二进制文件前，
请同时遵守所有第三方依赖的许可证要求。详情见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 致谢

- 原始 macOS 项目：[Mak5er/AirCard](https://github.com/Mak5er/AirCard)
- Windows 移植基础：[alrrstd/AirCard-Windows](https://github.com/alrrstd/AirCard-Windows)
- `pymobiledevice3` 及所有 AirLift / AirTraffic 研究贡献者
