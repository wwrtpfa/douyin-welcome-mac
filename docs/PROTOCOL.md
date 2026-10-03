# 消息接入与边界

应用启动独立 Chrome 持久化上下文，profile 位于应用自己的 Application Support 目录。
通过 Playwright 的 websocket / framereceived 事件读取网页收到的二进制消息。
网页本身完成连接、心跳和确认；本应用不生成签名、不导出登录 Cookie，不发送弹幕。

自编的有界 protobuf wire decoder 只读取必要字段，未引入第三方爬虫实现：

| 结构 | 字段 |
| --- | --- |
| PushFrame | 8: payload（可能 gzip） |
| Response | 1: repeated Message |
| Message | 1: method, 2: payload, 3: msgId |
| MemberMessage | 1: Common, 2: User, 5: isSetToAdmin, 10: action, 12: userId |
| Common | 2: msgId, 4: createTime |
| User | 1: id, 3: nickname, 1028: idStr |

字段编号调研参考：
https://github.com/saermart/DouyinLiveWebFetcher/blob/main/protobuf/douyin.proto
该参考项目许可为 AGPL-3.0，不把其爬虫源码复制进本项目，也不宣称它是 MIT。

正常成员事件接受缺省 action/0 与 1，跳过其他 action 和管理员设置消息；这些非官方语义需在真实房间进一步核验。
服务器超过 30 秒的历史消息不播报；缺少时间戳的消息只能按本地到达时间去重和过期。
昵称不是身份标识，去重使用 user ID。平台不保证每个观众都有进房消息。
“消息接收中”仅说明 WebSocket 收到了帧，不等于已验证收到进房事件。

本地联调脚本使用独立、临时 profile 和本地 WebSocket，验证真实 Chrome 到队列的链路；不代表抖音直播实测。
