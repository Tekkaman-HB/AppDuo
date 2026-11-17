# WorkBuddy 分身兼容性修复：创建签名与启动失败

> 当前修复以本文末尾“第三轮：找不到钥匙串”为准。第二轮的独立 HOME 方案已撤回，
> 请使用 `dist/AppDuo-0.1.9-workbuddy-keychain-fix-arm64.dmg`。

## 本机复现（2026-11-17）

- 已安装 AppDuo：0.1.9。
- WorkBuddy：5.11.3，Bundle ID `com.tencent.workbuddy.mac`，Electron 应用。
- 最初通用匹配规则：`hard_clone`，仅使用 `--user-data-dir` 参数；后续启动排查发现该参数不足以隔离 WorkBuddy，见下文。
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

以上是第一轮创建/签名验证，当时没有验证启动。后续启动测试及其边界见下文。


## 第二轮：创建成功但分身无法启动（2026-11-17）

用户界面报错：`系统未打开指定的分身，请检查分身应用是否完整。`
严格签名通过并不代表 Electron 可以启动。本机使用原版 WorkBuddy 5.11.3，
分别测试直接执行和与 AppDuo 相同的 `NSWorkspace.openApplication` 启动方式，确认存在三处兼容问题。

### 1. 不能用显示名覆盖 Electron 的内部应用名

之前把 `CFBundleName` 改成自定义显示名。Electron 使用内部应用名查找
`Contents/Frameworks/<名称> Helper.app`，因此直接启动崩溃：

```text
FATAL:electron/shell/app/electron_main_delegate_mac.mm:67
Unable to find helper app
```

修复：Electron 保留源应用的 `CFBundleName`（源应用没有该键时也不补造），
只修改 `CFBundleDisplayName`。非 Electron 应用保持原有重命名行为。

### 2. 不能批量重命名 Electron 的辅助可执行文件

仅修复内部应用名后，进程能存活，但仍没有主窗口。
在临时副本中恢复全部辅助可执行文件的原始文件名后，才实际出现主窗口。
原有兼容符号链接不足以保证辅助程序正常工作；仅恢复单一 crashpad 名称也没有解决问题。

修复：Electron 只单独重命名主进程，保留辅助可执行文件及对应
`CFBundleExecutable` 的原名；原生应用的既有批量重命名规则不变。

### 3. WorkBuddy 会覆盖通用 user-data-dir

检查安装包内的应用代码确认，WorkBuddy 自行调用 `app.setPath('userData', ...)`，
通用 `--user-data-dir` 参数不足以提供其配置隔离。
新增 `com.tencent.workbuddy.mac.yaml`，使用 WorkBuddy 支持的目录变量：

| 变量 | 分身目录下的路径 |
| --- | --- |
| `HOME` | `Home` |
| `TMPDIR` | `Tmp` |
| `WORKBUDDY_CONFIG_DIR` | `Config` |
| `CODEBUDDY_CONFIG_DIR` | `Config` |
| `WORKBUDDY_USER_DATA_DIR` | `UserData` |

新建分身也保留 `--user-data-dir=<分身数据目录>/UserData`。
更新旧 WorkBuddy 分身时只补齐缺失的环境变量，保留已有自定义覆盖值、原参数、
数据根目录、UUID、显示名和创建时间；不复制原版账号数据，不删除或迁移既有文件。
因此旧分身也需要用新引擎执行一次“更新”，仅更换 AppDuo GUI 不会改好旧分身包。

### 本机现有分身已修复

- 分身：`~/AppDuo/Apps/WorkBuddy 2.app`，显示名 `黄煜珂的小豆`。
- 更新前已备份应用包及 `clones.json`：
  `~/AppDuo/Backups/workbuddy-startup-20261117-231340/`。
- 备份应用使用 `.app.backup` 后缀，避免被作为另一个可启动副本注册。
- 更新后检查确认分身标识、名称、数据目录及创建时间不变。
- 没有修改 `/Applications/WorkBuddy.app` 或替换 `/Applications/AppDuo.app`，
  没有复制、删除原版账号数据。

### 本轮验证

1. 新策略生成的真实临时分身：`NSWorkspace` 回调路径确认为该分身，
   启动后 18 秒进程存活，`isFinishedLaunching` 为 true，检测到 1440×900 的可见主窗口。
2. 原地更新后的 `WorkBuddy 2.app`：同样检测到 1440×900 的可见主窗口，
   回调确认打开的是分身而非原版；测试结束后正常终止该分身。
   原版 WorkBuddy 进程仍保留。
3. 临时分身在自身 `Home`、`Config`、`UserData`、`Tmp` 下生成运行目录；
   原版及分身均通过 `codesign --verify --deep --strict`。
4. `python3 script/test_electron_compatibility.py`：4 项全部通过，覆盖
   Electron 内部名/辅助文件名、缺失内部名、原生应用命名和旧 WorkBuddy 环境变量迁移，
   并检查更新保留记录及数据标记。
5. 原有签名回归检查再次通过：裸资源包、资源篡改检测、有元数据资源包、
   损坏代码包拒绝，以及嵌套代码包。
6. Release CLI 同样运行上述 4 项回归并全部通过；新 GUI 包通过严格签名和资源检查，
   新 DMG 通过校验与只读挂载后的签名/资源检查，镜像内主程序及 WorkBuddy 配方与构建产物一致。
   `dist/SHA256SUMS` 已更新。
7. 添加 `Tests/CloneCoreTests/ElectronCompatibilityTests.swift`。
   本机缺少 XCTest 的限制仍在，这份 XCTest 未运行；不得将 CLI 回归结果表述为 XCTest 通过。

测试环境注意：Codex 工具进程继承了 `ELECTRON_RUN_AS_NODE=1`。
手动测试 Electron GUI 前必须从调用者环境中移除该变量，例如
`/usr/bin/env -u ELECTRON_RUN_AS_NODE <启动诊断程序>`；
仅从 `NSWorkspace.OpenConfiguration.environment` 字典中删除不足以清除继承值。

### 新 GUI 包

- `dist/AppDuo.app`：已包含创建与启动两轮修复。
- `dist/AppDuo-0.1.9-workbuddy-startup-fix-arm64.dmg`：本轮安装镜像。
- `dist/AppDuo-0.1.9-workbuddy-fix-arm64.dmg`：旧的仅创建/签名修复包，
  **不包含本轮启动修复**，不要混用。

先退出旧 AppDuo，再运行仓库内新版，或从新 DMG 手动替换安装。
不要再用旧版更新此分身，否则可能重新引入启动问题。
新构建仍为本地 ad-hoc 签名、未公证，并非新的官方版本。

边界：已验证真实窗口启动，但没有登录账号，也没有验证消息收发、通知、
插件、所有辅助工具和完整的账号隔离；不能据此保证所有业务功能或安全边界完全隔离。


## 第三轮：找不到钥匙串（2026-11-17）

用户在启动分身后看到系统提示：

```text
找不到钥匙串
找不到用于储存 “com.turingshield.identifying.guid.Local” 的钥匙串。
```

**不要为此点击“还原为默认”，不要重置/删除登录钥匙串。**

### 根因与修正

上一轮为 WorkBuddy 新增的 `HOME={{ATB_DATA_DIR}}/Home` 存在兼容问题：
macOS Security 无法在该合成 HOME 下解析现有的默认登录钥匙串。
此前的窗口启动测试没有覆盖 TuringShield 后续的钥匙串访问，不能据此保证应用完整可用。

只读复现，不读取任何钥匙串条目或密码：

```bash
/usr/bin/security default-keychain -d user
# 正常返回真实用户的 Library/Keychains/login.keychain-db

env HOME="$HOME/AppDuo/Data/WorkBuddy 2/Home" \
  /usr/bin/security default-keychain -d user
# security: SecKeychainCopyDomainDefault user: A default keychain could not be found.
```

本轮修正：

- WorkBuddy 配方不再注入 `HOME`，让系统使用正常登录用户目录定位钥匙串。
- 仍保留 `TMPDIR`、`WORKBUDDY_CONFIG_DIR`、`CODEBUDDY_CONFIG_DIR`、
  `WORKBUDDY_USER_DATA_DIR`，配置及 Electron userData 仍指向现有分身数据目录。
- 更新旧记录时，仅在新配方未设置 HOME 且旧值精确等于此前生成的
  `{{ATB_DATA_DIR}}/Home` 时移除该覆盖；显式自定义的其他 HOME 值保持不变。
- 不删除旧 `Home` 目录，不迁移、复制或重置任何钥匙串，不修改条目访问控制。
- 保留前两轮 Electron 内部名、辅助程序原名和资源签名修复。

### 现有分身与备份

已更新 `~/AppDuo/Apps/WorkBuddy 2.app`。
本轮更新前的应用包及记录备份：

```text
~/AppDuo/Backups/workbuddy-keychain-20261117-232109/
```

更新后分身 ID、名称、显示名、创建时间和配置/数据路径未变。
默认钥匙串及用户钥匙串搜索列表在测试前后逐字一致；未替换已安装 AppDuo。

### 验证及限制

- 新增无交互的 Security.framework 元数据测试：关闭该测试进程的钥匙串 UI，
  仅调用 `SecKeychainCopyDefault` / `SecKeychainGetPath`，
  确认新配方生成的启动器与正常用户环境返回同一默认钥匙串。
  不查询条目、不读取密码、不写入钥匙串、不解锁或修改权限。
- 新增旧 HOME 覆盖迁移测试，检查旧 Home 数据标记及记录身份保留；
  保留自定义 HOME 的回归测试仍通过。
- Debug 和 Release CLI 的 Python 集成回归均为 6 项通过。
- 更新后的真实分身再次出现 1440×900 可见主窗口，回调确认是分身本身；
  测试结束后关闭该分身。此项仅证明窗口启动，不等同于人工确认所有后续系统弹窗消失。
- 新 GUI 严格签名/资源检查、新 DMG 校验及只读挂载后的签名/资源检查通过；
  镜像内主程序及配方与构建产物一致，`dist/SHA256SUMS` 已更新。
- 新增/更新的 XCTest 仍未运行，原因仍为本机缺少 XCTest 工具链。

新版包：`dist/AppDuo-0.1.9-workbuddy-keychain-fix-arm64.dmg`，
GUI 应用仍为 `dist/AppDuo.app`。旧 `workbuddy-startup-fix` 包仍包含独立 HOME 设置，
不能再用它更新 WorkBuddy 分身。

这不是钥匙串隔离方案：系统钥匙串及依赖真实 HOME 的厂商共享认证机制并未虚拟化。
仅验证配置目录及 userData 的指定路径，不承诺所有账号状态完全隔离。
若之后出现“允许访问钥匙串”之类正常授权提示，应由用户判断是否授权，
本工具不代填系统密码或自动允许。完整登录、收发消息、通知、插件等业务仍未验证。
