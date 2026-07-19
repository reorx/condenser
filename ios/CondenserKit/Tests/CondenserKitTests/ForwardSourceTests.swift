import Testing
@testable import CondenserKit

// 转发消息的展示主体解析：来源频道/用户/署名回退链、隐藏来源、非转发消息。

private func forwardedMsg(
    fromChannelID: Int? = nil, fromChannelName: String? = nil,
    fromUserID: Int? = nil, fromUserName: String? = nil,
    postAuthor: String? = nil, isForwarded: Bool = true
) -> DisplayMessage {
    DisplayMessage(
        id: 1, channelID: 100, date: .init(timeIntervalSince1970: 1_784_000_000),
        isEdited: false, editDate: nil, senderID: nil, senderName: nil,
        text: "t", isAlbum: false, groupedID: nil, mediaItems: [],
        webpage: nil, isForwarded: isForwarded,
        forwardInfo: isForwarded ? ForwardInfo(
            fromChannelID: fromChannelID, fromChannelName: fromChannelName,
            fromUserID: fromUserID, fromUserName: fromUserName,
            fromMessageID: nil, originalDate: nil, postAuthor: postAuthor) : nil,
        views: nil, forwardsCount: nil, repliesCount: nil, rawMessageIDs: [1],
        isRead: nil, isSaved: nil, channel: nil)
}

@Suite("DisplayMessage.forwardSource")
struct ForwardSourceTests {
    @Test("来源频道：名称 + 频道 id 作为头像 peer")
    func channelSource() {
        let msg = forwardedMsg(fromChannelID: 999, fromChannelName: "SrcChan")
        let source = msg.forwardSource
        #expect(source?.name == "SrcChan")
        #expect(source?.peerID == 999)
    }

    @Test("来源用户：回退到用户名 + 用户 id")
    func userSource() {
        let msg = forwardedMsg(fromUserID: 777, fromUserName: "Alice")
        let source = msg.forwardSource
        #expect(source?.name == "Alice")
        #expect(source?.peerID == 777)
    }

    @Test("只有署名（post_author）：有名字但无头像 peer")
    func postAuthorOnly() {
        let msg = forwardedMsg(postAuthor: "编辑部")
        let source = msg.forwardSource
        #expect(source?.name == "编辑部")
        #expect(source?.peerID == nil)
    }

    @Test("隐藏来源（无任何名字）→ nil，卡片按普通转发降级")
    func hiddenSource() {
        #expect(forwardedMsg(fromChannelID: 999).forwardSource == nil)
    }

    @Test("非转发消息 → nil")
    func notForwarded() {
        #expect(forwardedMsg(isForwarded: false).forwardSource == nil)
    }
}
