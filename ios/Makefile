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
