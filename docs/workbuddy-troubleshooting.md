# WorkBuddy 分身创建失败：资源目录被误当成代码包签名

## 本机复现（2026-11-17）

- 已安装 AppDuo：0.1.9。
- WorkBuddy：5.11.3，Bundle ID `com.tencent.workbuddy.mac`，Electron 应用。
- 默认匹配规则：`hard_clone`，使用独立 `--user-data-dir` 参数。
- 未修复引擎在独立临时目录创建分身时，停在“重新签名并验证”：

```text
codesign 失败（1）
…/Contents/Resources/TuringShield.bundle: bundle format unrecognized, invalid, or unsuitable
```

这是本机稳定复现的问题；如果用户界面的实际报错不同，还需继续核对报错文字。

## 原因与修复

WorkBuddy 的 `Contents/Resources/TuringShield.bundle` 只有
`PrivacyInfo.xcprivacy`，没有 Info.plist 或可执行程序。

原实现仅根据扩展名选择 `.bundle` 目录，逐一交给 codesign。
这种不含 Bundle 元数据的资源目录不是可独立签名的代码包，因此 codesign 退出码为 1。

修复位于 `Sources/CloneCore/CloneEngine.swift`：

- 只处理真正的目录，排除符号链接。
- `.bundle` 目录需要具有 `Contents/Info.plist`、`Resources/Info.plist`
  或 `Info.plist`，才作为独立包重新签名。
- 无元数据的裸资源目录保留原样，由外层包的资源封印保护。
- 有元数据的资源包仍重新签名；`.app`、`.framework`、`.appex`、`.xpc`
  的签名失败仍然抛出错误。
- 保留最后的 `codesign --verify --deep --strict`，没有忽略签名错误。

不需要删除隐私声明文件、修改原版 WorkBuddy 或关闭系统安全功能。

## GUI 修复版（2026-11-17 本地重新打包）

已利用本机保留的 macOS 26.5 SDK 成功完成 Release GUI 构建，绕过默认
macOS 27.2 SDK 对缺失 `SwiftUIMacros` 插件的依赖，无需为本次打包修改系统 SDK 或安装完整 Xcode。

产物：

- 应用：`dist/AppDuo.app`。
- 安装镜像：`dist/AppDuo-0.1.9-workbuddy-fix-arm64.dmg`。
- 基于 0.1.9 的本地修复构建，Apple Silicon（arm64），并非新的官方版本。

先退出旧 AppDuo，再打开修复版：

```bash
open -n "$PWD/dist/AppDuo.app"
```

也可以打开 DMG，将应用安装到 `/Applications`（替换之前先退出旧版）。
本次打包没有自动替换已安装应用，也没有迁移或删除用户分身数据。
该构建为本地 ad-hoc 签名，未经过 Apple 公证，未配置 Sparkle 自动更新公钥。

复现打包：

```bash
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
CONFIGURATION=release bash script/build_and_run.sh --dmg
```

脚本默认生成 `dist/AppDuo-arm64.dmg`；本次分发镜像另行重命名以标识 WorkBuddy 修复。

## 修复后的 CLI（可选）

在本仓库中：

```bash
swift build --product AppDuoCLI
.build/debug/AppDuoCLI clone /Applications/WorkBuddy.app --name "WorkBuddy 2"
```

默认输出为 `~/AppDuo/Apps/WorkBuddy 2.app`，记录保存在默认 AppDuo 数据根目录。
如果同名分身已经存在，应先检查记录，不要手工删除已有账号数据。

创建后可重启 AppDuo 查看记录，或自行打开分身：

```bash
open "$HOME/AppDuo/Apps/WorkBuddy 2.app"
```

旧的图形版仍包含旧引擎，在换成修复版之前，不要用它更新或重新创建该分身。

## 验证结果与边界

本次已完成：

1. 未修复引擎对真实 WorkBuddy 稳定复现上述签名失败。
2. 修复后真实 WorkBuddy 分身创建成功，严格递归签名验证通过。
3. 分身中的隐私声明与原文件逐字节一致；原版 WorkBuddy 签名仍通过验证。
4. 独立 CLI 回归检查确认：裸资源包可克隆；修改克隆资源后严格验证会失败；
   有元数据的资源包和含可执行程序的嵌套代码包仍可签名；损坏的代码包仍被拒绝。
5. 在 `Tests/CloneCoreTests/SigningTests.swift` 增加三个对应 XCTest 回归测试。

补充验证：Release GUI 与 DMG 已成功生成，应用通过严格递归签名验证和
`--check-resources` 资源加载检查。DMG 校验和、只读挂载后的应用签名与资源加载均经过复核，
镜像内主程序与 `dist/AppDuo.app` 中主程序逐字节一致。

测试限制：本机仅选择了 Command Line Tools，没有完整 Xcode；独立 XCTest 构建报
`unable to resolve module dependency: 'XCTest'`，因此 XCTest 套件尚未运行。
最初 GUI 构建报缺少 `SwiftUIMacros` 插件的问题，已通过上述 macOS 26.5 SDK 构建方式解决。
在具备 XCTest 的工具链环境中仍应运行：

```bash
swift test --filter SigningTests
```

真实分身测试仅在独立临时目录执行，没有启动或登录该分身；账号登录、完整数据隔离、
通知及业务功能尚未验证，不能仅凭创建成功就保证多账号完全隔离。
