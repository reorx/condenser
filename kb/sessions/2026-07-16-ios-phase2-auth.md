---
created: 2026-07-16
tags:
  - ios
  - swiftui
  - auth
  - mobile
---

# iOS Phase 2：认证（TokenStore + AuthFlow + 登录页 + 401 骨架）

按 [2026-07-16-ios-reader-app.md](../plans/2026-07-16-ios-reader-app.md) 实施阶段 2，
BDD：先写 CondenserKit 行为测试（红）再实现（绿）。模拟器截图验证了登录页渲染；
授权全流程（web 密码登录 → 确认 → 回调）留待手动验证。

## CondenserKit（纯逻辑 + 13 个测试全绿）

- `Auth/AuthFlow.swift` — 纯函数集：
  - `normalizeServerAddress(_:)`：裸域名补 https、去空白/尾斜杠、拒绝非 http(s)
  - `authorizeURL(server:deviceName:)`：`<server>/authorize?device_name=`（百分号编码）
  - `parseCallback(_:)` → `Callback?`：`.authorized(token:name:)` / `.denied` / nil（畸形）
  - `callbackScheme = "condenser"` 常量供 app 层复用
- `Auth/TokenStore.swift`：
  - `SecureStore` 协议（read/write/remove）→ 生产 `KeychainStore`
    （kSecClassGenericPassword，service `com.reorx.condenser`，AfterFirstUnlock），
    测试注入 `InMemorySecureStore` fake —— Keychain 本身不做单测
  - `TokenStore` 门面：token 走 SecureStore，`serverURL` 走 UserDefaults（可注入 suite）；
    **`clearToken()` 保留 serverURL**（登出后重新登录预填地址）
- 删除了骨架期占位 `Greeting.swift` + 测试

## App target（UI 胶水）

- `Services/AuthSession.swift` — `@MainActor @Observable`：init 从 TokenStore 恢复会话；
  `completeLogin` / `signOut`（只清 token）/ `handleUnauthorized()`（清 token + notice
  "会话已失效"）。**401 接线留给 phase 3 的 APIClient**。
- `UI/LoginView.swift` — 服务器地址（预填上次或默认 condenser.reorx.com）+ 设备名
  （默认 `UIDevice.current.name`，iOS 16+ 返回通用 "iPhone xx"，可编辑）；
  用 SwiftUI 原生 `@Environment(\.webAuthenticationSession)`（而非手搭
  ASWebAuthenticationSession + presentationContextProvider），
  `preferredBrowserSession: .shared` 保 web cookie 复用；
  `canceledLogin` 静默留在登录页，denied/畸形回调显示错误文案。
- `UI/MainView.swift` — 登录后占位（host + 登出按钮），phase 3 换成 TabView。
- `CondenserApp.swift` — `session.isAuthenticated` 驱动 LoginView/MainView 切换，
  `.environment(session)` 注入。

## 备注 / 下一步

- `condenser://` URL scheme 早在 phase 1 的 project.yml 里就配好，无需改动。
- Phase 3（核心阅读）：APIClient（401 → `handleUnauthorized`）+ Models
  （对照 `frontend/src/lib/types.ts`）+ TimelineStore + 卡片 + 详情 sheet +
  滚动已读 + 新消息胶囊。
