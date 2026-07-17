SHELL := /bin/bash
DERIVED_DATA := .build/DerivedData
APP := $(DERIVED_DATA)/Build/Products/Debug-iphonesimulator/Condenser.app
BUNDLE_ID := com.reorx.condenser
# 覆盖示例：make run SIM="iPhone 17 Pro"
SIM ?= iPhone 17
# 构建用 generic destination：不依赖已安装的模拟器 runtime
XCODEBUILD := xcodebuild -project Condenser.xcodeproj -scheme Condenser \
	-destination 'generic/platform=iOS Simulator' -derivedDataPath $(DERIVED_DATA)

.PHONY: gen build test run dev device clean

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

# 真机构建 + 推送安装（签名参数在脚本内命令行覆盖，不动 project.yml）
# 用法：make device [TEAM_ID=ABCDE12345] [DEVICE="<设备名或UDID>"]
device: gen
	./scripts/device.sh

clean:
	rm -rf $(DERIVED_DATA) CondenserKit/.build Condenser.xcodeproj
