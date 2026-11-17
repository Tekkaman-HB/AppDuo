import XCTest
@testable import CloneCore

final class ElectronCompatibilityTests: XCTestCase {
    private func addElectronFramework(to app: URL) throws {
        let fm = FileManager.default
        let framework = app.appendingPathComponent("Contents/Frameworks/Electron Framework.framework")
        let version = framework.appendingPathComponent("Versions/A")
        let resources = version.appendingPathComponent("Resources")
        try fm.createDirectory(at: resources, withIntermediateDirectories: true)
        try RuntimeBuilder.compile("int electron_fixture(void) { return 0; }", output: version.appendingPathComponent("Electron Framework"), library: true)
        try Plist.write(["CFBundleIdentifier": "com.atb.test.electron-framework", "CFBundleExecutable": "Electron Framework", "CFBundlePackageType": "FMWK"], to: resources.appendingPathComponent("Info.plist"))
        try fm.createSymbolicLink(atPath: framework.appendingPathComponent("Versions/Current").path, withDestinationPath: "A")
        try fm.createSymbolicLink(atPath: framework.appendingPathComponent("Electron Framework").path, withDestinationPath: "Versions/Current/Electron Framework")
        try fm.createSymbolicLink(atPath: framework.appendingPathComponent("Resources").path, withDestinationPath: "Versions/Current/Resources")
    }

    func testElectronInternalNameAndHelperPathsSurviveCreateAndUpdate() throws {
        let (root, base) = try EngineTests().fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        try addElectronFramework(to: base.source)
        let sourcePlist = base.source.appendingPathComponent("Contents/Info.plist")
        var original = try Plist.read(sourcePlist)
        original["CFBundleName"] = "WorkBuddy"
        original["CFBundleDisplayName"] = "WorkBuddy"
        try Plist.write(original, to: sourcePlist)
        let helper = base.source.appendingPathComponent("Contents/Frameworks/WorkBuddy Helper.app")
        let helperExecutable = helper.appendingPathComponent("Contents/MacOS/WorkBuddy Helper")
        try FileManager.default.createDirectory(at: helperExecutable.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: base.source.appendingPathComponent("Contents/MacOS/Original"), to: helperExecutable)
        try Plist.write(["CFBundleIdentifier": "com.atb.test.helper", "CFBundleExecutable": "WorkBuddy Helper", "CFBundlePackageType": "APPL"], to: helper.appendingPathComponent("Contents/Info.plist"))
        var config = base
        config.recipe.appType = "electron"
        config.recipe.arguments = ["--user-data-dir={{ATB_DATA_DIR}}"]
        let marker = config.dataDirectory.appendingPathComponent("keep.txt")
        for (index, name) in ["中文分身", "另一个显示名"].enumerated() {
            config.displayName = name
            _ = try CloneEngine().build(config, updating: index > 0)
            if index == 0 { try Data("existing profile".utf8).write(to: marker) }
            let metadata = try Plist.read(config.destination.appendingPathComponent("Contents/Info.plist"))
            XCTAssertEqual(metadata["CFBundleName"] as? String, "WorkBuddy")
            XCTAssertEqual(metadata["CFBundleDisplayName"] as? String, name)
            XCTAssertEqual(metadata["CFBundleIdentifier"] as? String, config.bundleID)
            let internalName = try XCTUnwrap(metadata["CFBundleName"] as? String)
            let helperPath = config.destination.appendingPathComponent("Contents/Frameworks/\(internalName) Helper.app/Contents/MacOS/\(internalName) Helper")
            XCTAssertTrue(FileManager.default.isExecutableFile(atPath: helperPath.path))
            XCTAssertFalse(try helperPath.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink ?? true)
            let helperMetadata = try Plist.read(helperPath.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Info.plist"))
            XCTAssertEqual(helperMetadata["CFBundleExecutable"] as? String, "WorkBuddy Helper")
            let main = config.destination.appendingPathComponent("Contents/MacOS/" + config.name)
            XCTAssertTrue(FileManager.default.isExecutableFile(atPath: main.path))
            XCTAssertFalse(try main.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink ?? true)
            XCTAssertEqual(try Data(contentsOf: marker), Data("existing profile".utf8))
            try Command.run("/usr/bin/codesign", ["--verify", "--deep", "--strict", config.destination.path])
        }
        XCTAssertEqual(try Plist.read(sourcePlist)["CFBundleName"] as? String, "WorkBuddy")
    }

    func testElectronMissingInternalNameIsNotInvented() throws {
        let (root, config) = try EngineTests().fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        try addElectronFramework(to: config.source)
        _ = try CloneEngine().build(config)
        let metadata = try Plist.read(config.destination.appendingPathComponent("Contents/Info.plist"))
        XCTAssertNil(metadata["CFBundleName"])
        XCTAssertEqual(metadata["CFBundleDisplayName"] as? String, config.displayName)
    }

    func testWorkBuddyRecipeProvidesApplicationSpecificIsolation() throws {
        let recipe = try XCTUnwrap(Recipes.load().first { $0.bundleID == "com.tencent.workbuddy.mac" })
        XCTAssertNil(recipe.environment["HOME"])
        XCTAssertEqual(recipe.environment["TMPDIR"], "{{ATB_DATA_DIR}}/Tmp")
        XCTAssertEqual(recipe.environment["WORKBUDDY_CONFIG_DIR"], "{{ATB_DATA_DIR}}/Config")
        XCTAssertEqual(recipe.environment["CODEBUDDY_CONFIG_DIR"], "{{ATB_DATA_DIR}}/Config")
        XCTAssertEqual(recipe.environment["WORKBUDDY_USER_DATA_DIR"], "{{ATB_DATA_DIR}}/UserData")
    }

    func testLegacyWorkBuddyUpdateAddsIsolationWithoutReplacingOverrides() async throws {
        let (root, base) = try EngineTests().fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        var config = base
        config.recipe.bundleID = "com.tencent.workbuddy.mac"
        config.recipe.environment = ["HOME": "{{ATB_DATA_DIR}}/CustomHome"]
        let sourcePlist = config.source.appendingPathComponent("Contents/Info.plist")
        var metadata = try Plist.read(sourcePlist)
        metadata["CFBundleIdentifier"] = config.recipe.bundleID
        try Plist.write(metadata, to: sourcePlist)
        let repository = CloneRepository(root: root.appendingPathComponent("Records"))
        let before = try await repository.build(config, password: "", updating: false, log: { _ in })
        let marker = config.dataDirectory.appendingPathComponent("keep.txt")
        try Data("existing data".utf8).write(to: marker)
        let after = try await repository.build(before[0].configuration, password: "", updating: true, log: { _ in })
        XCTAssertEqual(after[0].id, before[0].id)
        XCTAssertEqual(after[0].createdAt, before[0].createdAt)
        XCTAssertEqual(after[0].configuration.dataDirectory, config.dataDirectory)
        XCTAssertEqual(after[0].configuration.recipe.environment["HOME"], "{{ATB_DATA_DIR}}/CustomHome")
        XCTAssertEqual(after[0].configuration.recipe.environment["WORKBUDDY_CONFIG_DIR"], "{{ATB_DATA_DIR}}/Config")
        XCTAssertEqual(after[0].configuration.recipe.environment["WORKBUDDY_USER_DATA_DIR"], "{{ATB_DATA_DIR}}/UserData")
        XCTAssertEqual(try Data(contentsOf: marker), Data("existing data".utf8))
    }

    func testLegacyWorkBuddyUpdateRemovesOnlyGeneratedHomeOverride() async throws {
        let (root, base) = try EngineTests().fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        var config = base
        config.recipe.bundleID = "com.tencent.workbuddy.mac"
        config.recipe.environment = ["HOME": "{{ATB_DATA_DIR}}/Home"]
        var metadata = try Plist.read(config.source.appendingPathComponent("Contents/Info.plist"))
        metadata["CFBundleIdentifier"] = config.recipe.bundleID
        try Plist.write(metadata, to: config.source.appendingPathComponent("Contents/Info.plist"))
        let repository = CloneRepository(root: root.appendingPathComponent("Records"))
        let before = try await repository.build(config, password: "", updating: false, log: { _ in })
        let marker = config.dataDirectory.appendingPathComponent("Home/keep.txt")
        try Data("existing home data".utf8).write(to: marker)
        let after = try await repository.build(before[0].configuration, password: "", updating: true, log: { _ in })
        XCTAssertNil(after[0].configuration.recipe.environment["HOME"])
        XCTAssertEqual(after[0].configuration.recipe.environment["WORKBUDDY_CONFIG_DIR"], "{{ATB_DATA_DIR}}/Config")
        XCTAssertEqual(after[0].id, before[0].id)
        XCTAssertEqual(after[0].createdAt, before[0].createdAt)
        XCTAssertEqual(try Data(contentsOf: marker), Data("existing home data".utf8))
    }

    func testNativeAppsStillUseCustomInternalName() throws {
        let (root, base) = try EngineTests().fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        var config = base
        config.displayName = "原生应用分身"
        _ = try CloneEngine().build(config)
        let metadata = try Plist.read(config.destination.appendingPathComponent("Contents/Info.plist"))
        XCTAssertEqual(metadata["CFBundleName"] as? String, config.displayName)
        XCTAssertEqual(metadata["CFBundleDisplayName"] as? String, config.displayName)
    }
}
