#!/bin/bash
# 真机构建 + 推送安装（make device 的实现，用法见 AGENTS.md「真机部署」）
#
# 环境变量：
#   TEAM_ID  签名用的开发者 Team ID（缺省时从钥匙串的 Apple Development 证书自动探测）
#   DEVICE   目标设备（名称 / UDID），缺省时自动选中唯一已连接的设备
set -euo pipefail
cd "$(dirname "$0")/.."

DERIVED_DATA=.build/DerivedData
APP=$DERIVED_DATA/Build/Products/Debug-iphoneos/Condenser.app
BUNDLE_ID=com.reorx.condenser

# ---- Team ID：env 优先，其次从钥匙串证书的 OU 字段探测 ----
if [[ -z "${TEAM_ID:-}" ]]; then
  TEAM_ID=$(security find-certificate -c "Apple Development" -p 2>/dev/null \
    | openssl x509 -noout -subject 2>/dev/null \
    | sed -n 's/.*OU *= *\([A-Z0-9]\{10\}\).*/\1/p' | head -1)
fi
if [[ -z "$TEAM_ID" ]]; then
  echo "error: 找不到 Team ID。先在 Xcode → Settings → Accounts 登录 Apple ID" >&2
  echo "       （生成 Apple Development 证书后可自动探测），或手动指定：" >&2
  echo "       make device TEAM_ID=ABCDE12345" >&2
  exit 1
fi
echo "==> Team ID: $TEAM_ID"

# ---- 选设备：解析出 UDID（DEVICE 可传名称或 UDID；缺省取唯一已连接的真机） ----
DEVICES_JSON=$(mktemp)
trap 'rm -f "$DEVICES_JSON"' EXIT
xcrun devicectl list devices --json-output "$DEVICES_JSON" >/dev/null
UDID=$(python3 - "$DEVICES_JSON" "${DEVICE:-}" <<'EOF'
import json, sys
want = sys.argv[2]
devices = json.load(open(sys.argv[1]))["result"]["devices"]
connected = [d for d in devices
             if d.get("connectionProperties", {}).get("tunnelState") == "connected"]
if want:
    connected = [d for d in connected
                 if want in (d["deviceProperties"]["name"],
                             d["hardwareProperties"]["udid"])]
    if not connected:
        sys.exit(f"error: 没有名为 / UDID 为 {want!r} 的已连接设备。")
if not connected:
    sys.exit("error: 没有已连接的 iPhone。用数据线连接并在手机上信任此电脑，"
             "开启开发者模式（设置 → 隐私与安全性 → 开发者模式）后重试。")
if len(connected) > 1:
    names = ", ".join(d["deviceProperties"]["name"] for d in connected)
    sys.exit(f"error: 检测到多台设备（{names}），用 make device DEVICE=<名称> 指定一台。")
print(connected[0]["hardwareProperties"]["udid"])
EOF
)
echo "==> Device: $UDID"

# ---- 构建：命令行覆盖 project.yml 的模拟器无签名配置 ----
# destination 必须指到具体设备（而非 generic/platform=iOS），
# -allowProvisioningDeviceRegistration 才能把这台设备注册进团队、生成 profile
# （免费 Personal Team 无法在开发者网站手动加设备，只有这条路）
set -o pipefail
xcodebuild -project Condenser.xcodeproj -scheme Condenser \
  -destination "platform=iOS,id=$UDID" \
  -derivedDataPath "$DERIVED_DATA" -configuration Debug \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  CODE_SIGN_IDENTITY="Apple Development" \
  -allowProvisioningUpdates \
  -allowProvisioningDeviceRegistration \
  build | xcbeautify

# ---- 安装 + 启动（启动失败不算错：手机锁屏 / 首次未信任证书时会失败） ----
xcrun devicectl device install app --device "$UDID" "$APP"
if ! xcrun devicectl device process launch --terminate-existing \
    --device "$UDID" "$BUNDLE_ID"; then
  echo "warn: 自动启动失败（手机可能锁屏）。若首次安装打不开，先在手机上信任证书：" >&2
  echo "      设置 → 通用 → VPN 与设备管理 → 信任你的开发者证书" >&2
fi
