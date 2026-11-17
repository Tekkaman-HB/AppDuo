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

## 当前可用方案：修复后的 CLI

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

限制：本机仅选择了 Command Line Tools，没有完整 Xcode；独立 XCTest 构建报
`unable to resolve module dependency: 'XCTest'`，GUI 构建报缺少 `SwiftUIMacros` 插件。
因此本次没有完成 XCTest 套件运行或 GUI 打包，也未替换 `/Applications/AppDuo.app`。
CLI 已成功编译和验证；在具备所需插件的完整 Xcode 环境中，可继续运行：

```bash
swift test --filter SigningTests
bash script/build_and_run.sh --build
```

真实分身测试仅在独立临时目录执行，没有启动或登录该分身；账号登录、完整数据隔离、
通知及业务功能尚未验证，不能仅凭创建成功就保证多账号完全隔离。
