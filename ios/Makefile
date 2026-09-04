SHELL := /bin/bash
DERIVED_DATA := .build/DerivedData
APP := $(DERIVED_DATA)/Build/Products/Debug-iphonesimulator/Condenser.app
BUNDLE_ID := com.reorx.condenser
# 覆盖示例：make run SIM="iPhone 17 Pro"
SIM ?= iPhone 17
# 构建用 generic destination：不依赖已安装的模拟器 runtime
XCODEBUILD := xcodebuild -project Condenser.xcodeproj -scheme Condenser \
	-destination 'generic/platform=iOS Simulator' -derivedDataPath $(DERIVED_DATA)

.PHONY: gen build test run dev device archive clean

# 从 project.yml 重新生成 Condenser.xcodeproj（xcodeproj 不入库）
gen:
	xcodegen

build: gen
	set -o pipefail && $(XCODEBUILD) -configuration Debug build | xcbeautify

# CondenserKit 纯逻辑单测（宿主 macOS 上跑 swift test）
test:
	cd CondenserKit && swift test

# 启动模拟器（未启动则 boot）→ 安装 → 重启 app（不触发构建）
run:
	@open -a Simulator
	@xcrun simctl bootstatus "$(SIM)" -b
	@xcrun simctl install "$(SIM)" $(APP)
	@xcrun simctl terminate "$(SIM)" $(BUNDLE_ID) 2>/dev/null || true
	@xcrun simctl launch "$(SIM)" $(BUNDLE_ID)

dev: build run

# 真机构建 + 推送安装（签名参数在脚本内命令行覆盖，不动 project.yml；
# Team ID 由脚本从 secrets.env 读，TEAM_ID= 可覆盖）
# 用法：make device [TEAM_ID=ABCDE12345] [DEVICE="<设备名或UDID>"]
device: gen
	./scripts/device.sh

# Apple 凭据统一从 ~/Sync/apple-developer/secrets.env 加载（变量含义与文件清单见
# 同目录 AGENTS.md）；本地不再硬编码任何凭据值。只取值不 export（xcodebuild 走参数）。
APPLE_SECRETS := $(HOME)/Sync/apple-developer/secrets.env

# App Store 归档 + 导出 ipa（Release；导出配置由 scripts/ExportOptions.template.plist
# 渲染 teamID 生成，产物见 EXPORT_OPTIONS）
# 产物：.build/DerivedData/export/Condenser.ipa；上传走 asc / Transporter
ARCHIVE := $(DERIVED_DATA)/Condenser.xcarchive
EXPORT_OPTIONS := $(DERIVED_DATA)/ExportOptions.plist
archive: gen
	set -o pipefail && source $(APPLE_SECRETS) && xcodebuild -project Condenser.xcodeproj -scheme Condenser \
		-destination 'generic/platform=iOS' -derivedDataPath $(DERIVED_DATA) \
		-configuration Release \
		DEVELOPMENT_TEAM=$$APPLE_TEAM_ID CODE_SIGN_STYLE=Automatic \
		CODE_SIGN_IDENTITY="Apple Development" \
		-allowProvisioningUpdates \
		archive -archivePath $(ARCHIVE) | xcbeautify
	source $(APPLE_SECRETS) && mkdir -p $(DERIVED_DATA) && \
		sed "s/__APPLE_TEAM_ID__/$$APPLE_TEAM_ID/" scripts/ExportOptions.template.plist > $(EXPORT_OPTIONS)
	set -o pipefail && xcodebuild -exportArchive -archivePath $(ARCHIVE) \
		-exportOptionsPlist $(EXPORT_OPTIONS) \
		-exportPath $(DERIVED_DATA)/export -allowProvisioningUpdates | xcbeautify

clean:
	rm -rf $(DERIVED_DATA) CondenserKit/.build Condenser.xcodeproj

# ---- Mac Catalyst（plan 2026-09-04）：同一 scheme、同一 DerivedData，换 destination ----
# 产物：$(MAC_APP)。App Sandbox entitlements 已挂（Condenser-macCatalyst.entitlements）。
# ⚠️ 缺省用团队签名（Apple Development + 自动 profile，首次会把这台 Mac 注册进团队），
# 不是 project.yml 的 ad-hoc "-"：Catalyst 走 data-protection keychain，ad-hoc 签名没有
# keychain-access-groups entitlement，token 写 Keychain 静默失败（-34018），表现为
# 每次重启都回到登录页。只想编译不想碰账号：make build-mac MAC_SIGN=adhoc
MAC_APP := $(DERIVED_DATA)/Build/Products/Debug-maccatalyst/Condenser.app
# destination 是这台 Mac 而不是 generic：-allowProvisioningDeviceRegistration 只对具体设备生效
# （generic 下 Xcode 报「Your team has no devices」）
XCODEBUILD_MAC := xcodebuild -project Condenser.xcodeproj -scheme Condenser \
	-destination 'platform=macOS,variant=Mac Catalyst' -derivedDataPath $(DERIVED_DATA)
MAC_SIGN ?= team

.PHONY: build-mac run-mac dev-mac

build-mac: gen
ifeq ($(MAC_SIGN),adhoc)
	set -o pipefail && $(XCODEBUILD_MAC) -configuration Debug build | xcbeautify
else
	set -o pipefail && source $(APPLE_SECRETS) && $(XCODEBUILD_MAC) -configuration Debug \
		DEVELOPMENT_TEAM=$$APPLE_TEAM_ID CODE_SIGN_STYLE=Automatic \
		CODE_SIGN_IDENTITY="Apple Development" \
		-allowProvisioningUpdates -allowProvisioningDeviceRegistration \
		build | xcbeautify
endif

# 直接执行二进制而不是 `open`：这样 CONDENSER_DEBUG_SERVER / _TOKEN / _ROUTE 这些
# 走查环境变量能原样传进去（`open` 不继承 shell 环境）。
# 上一个实例用 AppleScript 优雅退出，⚠️ 不要 pkill：SIGTERM 在 macOS 眼里是异常退出，
# 下次启动会先弹一个模态的「Condenser quit unexpectedly」把主窗口挡住，走查全部失效。
run-mac:
	@osascript -e 'tell application id "$(BUNDLE_ID)" to quit' >/dev/null 2>&1 || true
	@sleep 1
	@"$(MAC_APP)/Contents/MacOS/Condenser" >/dev/null 2>&1 &

dev-mac: build-mac run-mac
