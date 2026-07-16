import SwiftUI

@main
struct CondenserApp: App {
    @State private var session = AuthSession()

    var body: some Scene {
        WindowGroup {
            Group {
                if session.isAuthenticated {
                    MainView()
                } else {
                    LoginView()
                }
            }
            .environment(session)
        }
    }
}
