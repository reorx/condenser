#!/bin/bash
# 真机构建 + 推送安装（make device 的实现，用法见 AGENTS.md「真机部署」）
#
# 环境变量：
#   TEAM_ID  签名用的开发者 Team ID（缺省从 ~/Sync/apple-developer/secrets.env
#            的 APPLE_TEAM_ID 读——Apple 凭据唯一权威来源，见该目录 AGENTS.md）
#   DEVICE   目标设备（名称 / UDID），缺省时自动选中唯一已连接的设备
set -euo pipefail
cd "$(dirname "$0")/.."

DERIVED_DATA=.build/DerivedData
APP=$DERIVED_DATA/Build/Products/Debug-iphoneos/Condenser.app
BUNDLE_ID=com.reorx.condenser

# ---- Team ID：从 secrets.env 的 APPLE_TEAM_ID 读（子 shell 取值，不污染环境），env 可覆盖 ----
# 不再从钥匙串自动探测：钥匙串里同时存在旧免费 Personal Team 的证书，
# find-certificate 取首个匹配会探错。付费 Team 的 profile 一年有效，没有 7 天重装问题。
# 证书缺失时不预检——Automatic + -allowProvisioningUpdates 下 Xcode 会自动补证书/给出准确报错。
if [[ -z "${TEAM_ID:-}" ]]; then
  TEAM_ID=$(source "$HOME/Sync/apple-developer/secrets.env" && echo "$APPLE_TEAM_ID")
fi
[[ -n "$TEAM_ID" ]] || { echo "error: TEAM_ID 为空——检查 ~/Sync/apple-developer/secrets.env 的 APPLE_TEAM_ID" >&2; exit 1; }
echo "==> Team ID: $TEAM_ID"

# ---- 选设备：解析出 UDID（DEVICE 可传名称或 UDID；缺省取唯一已配对的真机） ----
# 已配对设备即可：USB 直连是 connected，Wi-Fi（首次 USB 配对后）平时是 disconnected，
# devicectl 执行命令时会按需建立 tunnel，无需预先 connected
DEVICES_JSON=$(mktemp)
trap 'rm -f "$DEVICES_JSON"' EXIT
xcrun devicectl list devices --json-output "$DEVICES_JSON" >/dev/null
UDID=$(python3 - "$DEVICES_JSON" "${DEVICE:-}" <<'EOF'
import json, sys
want = sys.argv[2]
devices = json.load(open(sys.argv[1]))["result"]["devices"]
paired = [d for d in devices
          if d.get("connectionProperties", {}).get("pairingState") == "paired"]
if want:
    paired = [d for d in paired
              if want in (d["deviceProperties"]["name"],
                          d["hardwareProperties"]["udid"])]
    if not paired:
        sys.exit(f"error: 没有名为 / UDID 为 {want!r} 的已配对设备。")
if not paired:
    sys.exit("error: 没有已配对的 iPhone。用数据线连接并在手机上信任此电脑，"
             "开启开发者模式（设置 → 隐私与安全性 → 开发者模式）后重试。")
if len(paired) > 1:
    # 多台时优先 tunnel 已连接的（通常是 USB 直连那台）
    connected = [d for d in paired
                 if d.get("connectionProperties", {}).get("tunnelState") == "connected"]
    if len(connected) == 1:
        paired = connected
    else:
        names = ", ".join(d["deviceProperties"]["name"] for d in paired)
        sys.exit(f"error: 检测到多台设备（{names}），用 make device DEVICE=<名称> 指定一台。")
print(paired[0]["hardwareProperties"]["udid"])
EOF
)
echo "==> Device: $UDID"

# ---- 构建：命令行覆盖 project.yml 的模拟器无签名配置 ----
# destination 必须指到具体设备（而非 generic/platform=iOS），
# -allowProvisioningDeviceRegistration 把新设备自动注册进团队、生成 profile
# （付费 Team 也可在开发者网站手动加设备，但这条路免去手工步骤）
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
# --timeout：Wi-Fi 设备不可达（不在同一局域网 / 手机休眠）时快速失败而不是无限等
xcrun devicectl device install app --timeout 300 --device "$UDID" "$APP"
if ! xcrun devicectl device process launch --terminate-existing \
    --timeout 60 --device "$UDID" "$BUNDLE_ID"; then
  echo "warn: 自动启动失败（手机可能锁屏）。若首次安装打不开，先在手机上信任证书：" >&2
  echo "      设置 → 通用 → VPN 与设备管理 → 信任你的开发者证书" >&2
fi
