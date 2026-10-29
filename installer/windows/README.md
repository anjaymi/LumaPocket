# LumaPocket Windows 安装助手 0.1.1

独立 Windows EXE，为每个用户准备自己的 GitHub 签名仓库，并通过 USB 安装已经为当前
设备签名的 IPA。签名链路仍为实验版，构建和离线测试不代表真实 Apple 账号或设备安装
已经验证。

安装助手支持连接 iPhone 和 iPad。当前应用包同时声明支持两种设备，最低系统版本为
iOS / iPadOS 15.0；iPad 已完成真机安装，iPhone 仍需实际设备验证。

每位用户只需登录自己的账号。助手会从 `anjaymi/LumaPocket` 模板创建个人签名仓库，
并从其公开 Releases 下载已经编译好的最新版未签名 IPA，再为自己的设备重签。
不需要复制 Flutter 源码，也不需要自己编译。通配符、画师库已包含在应用包里。

## 使用

1. 打开 `LumaPocket-Installer.exe`。首次使用会自动下载并校验官方便携工具。
2. 安装 Apple 官方的“Apple 设备”应用，用数据线连接 iPhone / iPad、解锁并信任电脑，点击读取设备。
3. 在首次签名页登录自己的 GitHub 账号，填写自己的 Apple 账号邮箱。程序会在个人账号下
   创建公开的 `LumaPocket-Cloud` 仓库，个人签名文件加密保存。
4. 点击开始授权，在本机窗口输入密码和验证码。首次云端签名通过后，程序下载签名 IPA。
5. 在安装页点击“安装到所选设备”。按 iPhone / iPad 系统提示启用开发者模式或信任开发者。
   若出现“不受信任的开发者”，到“设置 → 通用 → VPN 与设备管理 → 开发者 App”，
   选择自己用于签名的 Apple 账号并信任。验证时保持联网。若随后提示开发者模式，
   到“设置 → 隐私与安全性 → 开发者模式”开启，并按系统提示重启。

已有签名 IPA 可直接在安装页选择，不必重新签名。未签名、过期、未包含当前设备或应用
标识不匹配的描述文件会被拦下。任意第三方 IPA 的重新签名不在此工具的签名范围内。

若出现 Apple 错误 7460，说明现有证书或未完成的证书申请占用了名额。工具保留加密会话，
不会自动撤销其他证书；需先处理现有证书，再继续。不要反复重新登录。

免费签名有有效期；GitHub 生成新的签名文件后，还需要通过本工具将新 IPA 安装刷新到
设备。账号失效或 Apple 要求重新验证时，需要本人再次授权。

## 本机数据

- 程序数据：`%LOCALAPPDATA%\LumaPocketInstaller`
- IPA：`downloads\<GitHub用户名>`，也可用“另存为”导出。
- GitHub OAuth 凭据和状态密钥：当前 Windows 用户的 DPAPI 加密；与系统 GitHub CLI
  登录分开管理。不同 GitHub 账号和仓库的签名状态分别保存。
- 不要将个人数据目录交给朋友；分享 EXE 即可。每位朋友登录自己的账号。

Apple 官方根证书缺失时，工具会解释影响并征得用户同意后，才添加到当前用户证书库。
设备驱动通过 Apple 官方渠道安装，不包含在 EXE 中。
如缺少 Visual C++ x64 运行库，界面的“Windows 运行库”链接会打开 Microsoft 官方说明。

## 构建

使用 Windows 10/11 x64、Python 3.12。创建独立虚拟环境后，运行
`python -m pip install --no-deps -r requirements-lock.txt`，只安装锁定的最小依赖集合。
本工具只使用 pymobiledevice3 的 USB、配对和安装 API，不包含其可选开发工具。

运行 `python fetch_build_assets.py --output .build/resources`，取得并校验公开签名组件和
Apple 官方根证书。签名运行库来自仓库中的 `signing/windows-runtime.zip`。

`prepare_build.py` 只暂存公开源文件和指定资源，不复制个人状态目录。`build_installer.py`
使用 PyInstaller 打包，并嵌入可导出的源码与第三方说明。构建参数指定授权资源目录、输出
目录和应用图标，运行 `--help` 查看参数。

GitHub 浏览器授权期间，官方 CLI 会在本工具专用的临时目录生成登录配置。工具读取后将
令牌转存为当前 Windows 用户的 DPAPI 密文，并清除临时目录；异常退出后下次启动也会清理。

签名工具的固定源码、完整兼容补丁和构建出处见
[兼容版本](https://github.com/anjaymi/LumaPocket/releases/tag/signer-compat-20261029-r2)。
