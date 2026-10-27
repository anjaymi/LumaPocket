# GitHub 免费重签实验

这是一条待真实 Apple 账号和 iPhone 验证的实验链路。离线工具检查、密码学测试通过，
不代表 Apple 已经签发了可用的免费描述文件。手机上的安装／签名刷新仍需设备参与。

## 首次设置（Windows）

电脑需要可用的 Python 3.9+、Git for Windows 和已登录的 GitHub CLI。
仓库里的启动脚本会优先使用这台电脑已有的 Codex Python。
Windows 工具使用本仓库中经过校验的 Swift 6.0.3 便携运行库；系统仍需 Microsoft
Visual C++ 2015–2022 x64 运行库。无需安装完整 Swift 工具链或准备 Mac。

在仓库根目录打开终端：

```bat
signing\start.cmd check
signing\start.cmd authorize
```

`authorize` 会在本机终端依次要求手机 UDID、Apple 账号、密码和二次验证码。
UDID 可从 Apple Devices／iTunes 中查看；序列号不是 UDID。
Apple 密码由 SideSign 的本机交互提示读取，不保存到仓库或 GitHub Secrets。
本实验仅支持账号中恰好有一个免费 Personal Team 的情况。

工具会创建或复用本应用的开发证书、登记这一部手机、申请描述文件，随后把加密状态
通过标准输入写入本仓库的两个 Secrets：`IOS_SIGNING_PASSPHRASE` 和
`IOS_SIGNING_STATE_BASE64`。它不会撤销其他应用使用的证书；名额不足时会停止。

授权脚本会启动首轮手动重签并等待结果。只有当前授权对应的产物通过验证后，才设置
`FREE_SIGNING_ENABLED=true` 开启定期检查。如果网络断开或任务排队较久，可稍后执行：

```bat
signing\start.cmd enable
```

本机状态位于 Git 忽略的 `.lumapocket-signing`。Windows 上的解密密钥由当前用户的
DPAPI 保护；请保留这个目录，以便下载和解密自己的签名包。
如果本机授权已经成功保存，而上传 Secrets 时网络中断，可执行
`signing\start.cmd publish` 重试上传和首轮验证，无需再次输入 Apple 密码。

## 自动任务做什么

- 每天约 **香港时间 10:37** 检查，描述文件剩余不超过 48 小时时尝试续签。
- 从最近成功任务恢复加密会话和证书，向 Apple 获取有效描述文件。
- 核对团队、App ID、手机 UDID、证书、有效期，然后重签当前应用。
- 用 Apple 原生 `codesign` 检查完整性，同时检查 ARM64 架构和离线分词符号。
- 在成功产物中保存加密状态和加密 IPA。状态包含对应的未签名 IPA，供原始构建产物
  过期后继续使用。新源码版本需要先完成一次 `iOS self-test` 构建。

账号尚未配置时定期任务不会启用。GitHub 定时任务可能延迟；公共仓库长期无活动时
定时任务也可能被停用。登录会话失效、需要二次验证或 Apple 未延长到期时间时，任务
会失败并给出原因，不会把旧描述文件当作续签成功。

## 获取与安装结果

```bat
signing\start.cmd download
```

脚本会校验 GitHub 产物和 IPA 哈希，解密到本机私有目录，并显示完整文件路径。
安装时应保留包内签名。重新使用其他工具签名会改变被验证的签名身份。
例如，在已配对的电脑上，`pymobiledevice3` 可以通过手机安装服务安装现成 IPA：

```text
python -m pymobiledevice3 apps install --udid YOUR_UDID PATH_TO_SIGNED_IPA
```

这个安装依赖不由实验脚本自动安装，且本项目尚未做真机安装测试。免费签名仍受
Apple 的七天有效期限制，云端任务不会直接修改手机上已安装应用的签名。

## 停用与重新授权

```bat
signing\start.cmd disable
signing\start.cmd authorize
```

重新授权会保留同一团队和应用标识，复用已有证书，并重新执行手动验证。
如果最近的未签名构建已过期而又需要重置状态，请先运行一次 `iOS self-test`。

## 验证与来源

`Free signing experiment` 的 `validate` 模式在 Windows 和 macOS 运行无账号测试，
检查归档安全、错误账号／设备、到期判断、私密日志隔离、DPAPI／GPG 和真实
CSR、PKCS#12 操作。虚拟证书只用于离线测试，不是 Apple 开发证书。

- [SideSign v0.1.7](https://github.com/SideStore/SideSign/tree/10b446fc6fc47fe81b60879dfb126d0c8098ec29)
- [Apple 免费账号限制](https://developer.apple.com/help/account/basics/about-your-developer-account)
- [SideStore Anisette 说明](https://docs.sidestore.io/docs/advanced/anisette)
- [GitHub 定时任务说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [pymobiledevice3 安装命令实现](https://github.com/doronz88/pymobiledevice3/blob/master/pymobiledevice3/cli/apps.py)

工具下载固定版本并验证 SHA-256。Swift 便携库来自经过 Apple Authenticode 验证的
官方 6.0.3 安装包；其来源、校验值和 Swift／ICU 许可包含在 `windows-runtime.zip` 中。
上游 SideSign 使用 GPL-3.0，工具与应用代码分开运行。
