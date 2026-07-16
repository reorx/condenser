import Testing
@testable import CondenserKit

@Test func greetingMessage() {
    #expect(Greeting().message(for: "World") == "Hello, World!")
}
