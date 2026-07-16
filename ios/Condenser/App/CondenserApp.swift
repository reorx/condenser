import SwiftUI
import CondenserKit

@main
struct CondenserApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

struct ContentView: View {
    var body: some View {
        Text(Greeting().message(for: "Condenser"))
            .padding(40)
    }
}
