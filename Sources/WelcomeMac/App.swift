import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct Settings: Codable {
    var room = ""
    var mode = "system"
    var reference_audio = ""
    var reference_text = ""
    var template = "欢迎{name}，欢迎来到直播间！"
    var interval = 8
    var dedup_seconds = 600
    var max_age = 30
    var max_queue = 5
    var volume = 0.7
    var output_device = ""
    var blocked_words = ""
    var model = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit"
}

struct Activity: Identifiable {
    let id = UUID()
    let time = Date()
    let message: String
    let level: String
}

final class AppModel: ObservableObject {
    @Published var settings = Settings()
    @Published var ready = false
    @Published var connection = "disconnected"
    @Published var detail = "未连接直播间"
    @Published var devices: [String] = []
    @Published var entries: [Activity] = []
    @Published var paused = false
    @Published var phase = "idle"
    @Published var speaking = ""
    @Published var received = 0
    @Published var spoken = 0
    @Published var pending = 0
    @Published var skipped = 0
    @Published var saveMessage = ""
    @Published var errorMessage: String?
    var process: Process?
    private var input: FileHandle?
    private var buffer = Data()
    private var shuttingDown = false
    var didStop: (() -> Void)?

    var connectionLabel: String {
        switch connection {
        case "receiving": return "消息接收中"
        case "connecting": return "正在连接"
        case "waiting": return "等待直播消息"
        default: return "尚未连接"
        }
    }

    func start() {
        guard process == nil else { return }
        let resources = Bundle.main.resourceURL!
        let runtimeFile = resources.appendingPathComponent("runtime-path.txt")
        let project = (try? String(contentsOf: runtimeFile, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
            ?? ProcessInfo.processInfo.environment["WELCOME_PROJECT_ROOT"] ?? FileManager.default.currentDirectoryPath
        let python = project + "/.venv/bin/python"
        guard FileManager.default.isExecutableFile(atPath: python) else {
            record("本地运行环境不存在，请在项目目录执行 scripts/setup.sh 后重新构建。", "error")
            return
        }
        let backend = FileManager.default.fileExists(atPath: resources.appendingPathComponent("backend").path)
            ? resources.appendingPathComponent("backend").path : project + "/backend"
        let child = Process()
        child.executableURL = URL(fileURLWithPath: python)
        child.arguments = ["-u", "-m", "welcome_assistant"]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = backend
        environment["PYTHONUNBUFFERED"] = "1"
        environment["TOKENIZERS_PARALLELISM"] = "false"
        child.environment = environment
        child.currentDirectoryURL = URL(fileURLWithPath: project)
        let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        child.standardInput = stdin
        child.standardOutput = stdout
        child.standardError = stderr
        input = stdin.fileHandleForWriting
        stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.consume(data) }
        }
        stderr.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            // Keep internal diagnostics away from the activity feed.
        }
        child.terminationHandler = { [weak self] child in
            DispatchQueue.main.async {
                guard let self else { return }
                self.ready = false
                self.process = nil
                if !self.shuttingDown { self.record("后台服务已退出（\(child.terminationStatus)）。请退出后重新打开应用。", "error") }
                self.didStop?()
            }
        }
        do {
            try child.run()
            process = child
        } catch { record("无法启动后台服务：\(error.localizedDescription)", "error") }
    }

    private func consume(_ data: Data) {
        buffer.append(data)
        while let newline = buffer.firstIndex(of: 10) {
            let line = buffer.prefix(upTo: newline)
            buffer.removeSubrange(...newline)
            guard let event = try? JSONSerialization.jsonObject(with: line) as? [String: Any], let type = event["type"] as? String else { continue }
            switch type {
            case "ready":
                if let raw = event["settings"], let data = try? JSONSerialization.data(withJSONObject: raw), let settings = try? JSONDecoder().decode(Settings.self, from: data) { self.settings = settings }
                ready = true
                record("欢迎助手已就绪。先试听，再连接直播间。", "info")
            case "devices":
                devices = (event["devices"] as? [[String: String]] ?? []).compactMap { $0["name"] }.reduce(into: []) { if !$0.contains($1) { $0.append($1) } }
            case "connection":
                connection = event["state"] as? String ?? "disconnected"
                detail = event["detail"] as? String ?? ""
                record(detail, "info")
            case "queue":
                pending = event["pending"] as? Int ?? 0
                received = event["received"] as? Int ?? 0
                spoken = event["spoken"] as? Int ?? 0
                skipped = event["skipped"] as? Int ?? 0
                paused = event["paused"] as? Bool ?? false
                phase = event["phase"] as? String ?? "idle"
                speaking = event["text"] as? String ?? ""
            case "arrival":
                record("\((event["preview"] as? Bool ?? false) ? "试听" : "进房") · \(event["nickname"] as? String ?? "")", "arrival")
            case "log": record(event["message"] as? String ?? "", event["level"] as? String ?? "info")
            case "saved": saveMessage = "设置已保存"
            default: break
            }
        }
    }

    func record(_ message: String, _ level: String) {
        entries.insert(Activity(message: message, level: level), at: 0)
        if entries.count > 150 { entries.removeLast(entries.count - 150) }
        if level == "error" { errorMessage = message }
    }

    func send(_ command: String, extra: [String: Any] = [:]) {
        guard let input else { return }
        var payload = extra
        payload["command"] = command
        guard var data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        data.append(10)
        do { try input.write(contentsOf: data) }
        catch { if !shuttingDown { record("后台通信中断，请重新打开应用。", "error") } }
    }

    @discardableResult func save() -> Bool {
        guard settings.template.contains("{name}"), settings.template.count <= 100 else {
            record("欢迎语需要包含 {name}，且不超过 100 字。", "error")
            return false
        }
        guard let data = try? JSONEncoder().encode(settings), let value = try? JSONSerialization.jsonObject(with: data) else { return false }
        saveMessage = ""
        send("save", extra: ["settings": value])
        return true
    }

    func action(_ command: String, name: String = "新朋友") {
        if save() { send(command, extra: ["name": name]) }
    }

    func chooseRecording() {
        let picker = NSOpenPanel()
        picker.allowedContentTypes = [.wav, .aiff, .mpeg4Audio, .mp3]
        picker.allowsMultipleSelection = false
        picker.canChooseDirectories = false
        picker.message = "选择你自己的干净录音，3～30 秒，推荐 10～20 秒。"
        guard picker.runModal() == .OK, let url = picker.url else { return }
        do {
            let folder = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/DouyinWelcome/voice", isDirectory: true)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            // MLX/soundfile needs PCM. Convert compressed uploads at import time.
            let target = folder.appendingPathComponent(UUID().uuidString + ".wav")
            let converter = Process()
            converter.executableURL = URL(fileURLWithPath: "/usr/bin/afconvert")
            converter.arguments = ["-f", "WAVE", "-d", "LEI16@24000", "-c", "1", url.path, target.path]
            let errorPipe = Pipe()
            converter.standardError = errorPipe
            try converter.run()
            converter.waitUntilExit()
            guard converter.terminationStatus == 0 else {
                let detail = String(data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "未知格式"
                throw NSError(domain: "WelcomeMac", code: 1, userInfo: [NSLocalizedDescriptionKey: "无法转换录音：\(detail.trimmingCharacters(in: .whitespacesAndNewlines))"])
            }
            settings.reference_audio = target.path
            save()
        } catch { record("无法导入录音：\(error.localizedDescription)", "error") }
    }

    func shutdown(completion: @escaping () -> Void) {
        shuttingDown = true
        guard let process, process.isRunning else { completion(); return }
        didStop = completion
        send("shutdown")
        try? input?.close()
        let pid = process.processIdentifier
        DispatchQueue.main.asyncAfter(deadline: .now() + 12) { [weak self] in
            guard let self, self.process?.isRunning == true else { return }
            // Backend owns a separate process group, never the user's Chrome session.
            kill(-pid, SIGTERM)
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                if self.process?.isRunning == true { kill(-pid, SIGKILL) }
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    static weak var model: AppModel?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model = Self.model, model.process?.isRunning == true else { return .terminateNow }
        model.shutdown { sender.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct WelcomeMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel()
    var body: some Scene {
        WindowGroup("迎声 · 直播欢迎助手") {
            ContentView(model: model)
                .onAppear { AppDelegate.model = model; model.start(); NSApp.activate(ignoringOtherApps: true) }
                .frame(minWidth: 940, minHeight: 700)
                .alert("需要处理", isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })) {
                    Button("知道了") { model.errorMessage = nil }
                } message: { Text(model.errorMessage ?? "") }
        }
        .defaultSize(width: 1080, height: 780)
        .windowStyle(.hiddenTitleBar)
        .commands { CommandGroup(replacing: .newItem) {} }
    }
}

private let accent = Color(red: 0.17, green: 0.42, blue: 0.34)

struct ContentView: View {
    @ObservedObject var model: AppModel
    @State private var tab = "live"
    @State private var testName = "小明"
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 10) {
                    Image(systemName: "waveform").font(.title2).foregroundStyle(accent)
                    Text("迎声").font(.system(size: 25, weight: .semibold, design: .rounded))
                }.padding(.top, 32).padding(.bottom, 2)
                Text("让每一次到来\n都有你的声音。")
                    .font(.system(size: 12)).foregroundStyle(.secondary).lineSpacing(5).padding(.bottom, 24)
                nav("live", "直播工作台", "dot.radiowaves.left.and.right")
                nav("voice", "我的声音", "waveform.circle")
                nav("settings", "播报与音频", "slider.horizontal.3")
                Spacer()
                HStack(spacing: 7) {
                    Circle().fill(model.ready ? accent : .orange).frame(width: 6, height: 6)
                    Text(model.ready ? "本地服务已就绪" : "正在准备本地服务").font(.caption)
                }.foregroundStyle(.secondary)
                Text("Apple Silicon · 本地优先")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }.padding(22).frame(width: 190).background(Color(nsColor: .controlBackgroundColor))
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(tab == "live" ? "直播工作台" : tab == "voice" ? "我的声音" : "播报与音频")
                                .font(.system(size: 29, weight: .semibold))
                            Text(tab == "live" ? "先试听，再连接直播间。欢迎交给迎声，你专心直播。" : tab == "voice" ? "用一段自己的原声，生成新的欢迎语。" : "控制节奏，并把声音送到正确的地方。")
                                .font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text("本地测试版 0.1").font(.caption).padding(.horizontal, 10).padding(.vertical, 6).background(accent.opacity(0.08), in: Capsule()).foregroundStyle(accent)
                    }
                    if tab == "live" { live }
                    else if tab == "voice" { voice }
                    else { settings }
                }.padding(32)
            }.background(Color(nsColor: .windowBackgroundColor))
        }.tint(accent)
    }

    func nav(_ key: String, _ title: String, _ icon: String) -> some View {
        Button { tab = key } label: {
            Label(title, systemImage: icon).font(.system(size: 13, weight: tab == key ? .semibold : .regular))
                .frame(maxWidth: .infinity, alignment: .leading).padding(11)
                .background(tab == key ? accent.opacity(0.10) : .clear, in: RoundedRectangle(cornerRadius: 9))
                .foregroundStyle(tab == key ? accent : .secondary)
        }.buttonStyle(.plain)
    }

    func card<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title).font(.system(size: 15, weight: .semibold))
            content()
        }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.primary.opacity(0.055)))
    }

    var live: some View {
        VStack(spacing: 20) {
            card("01  连接你的直播间") {
                HStack {
                    TextField("https://live.douyin.com/直播间号码", text: $model.settings.room)
                        .textFieldStyle(.roundedBorder)
                    Button(model.connection == "disconnected" ? "连接直播间" : "重新连接") { model.action("connect") }
                        .buttonStyle(.borderedProminent).disabled(!model.ready || model.settings.room.isEmpty)
                    if model.connection != "disconnected" { Button("断开") { model.send("disconnect") } }
                }
                HStack(spacing: 8) {
                    Circle().fill(model.connection == "receiving" ? accent : Color.orange).frame(width: 7, height: 7)
                    Text(model.connectionLabel).fontWeight(.medium)
                    Text("· " + model.detail).foregroundStyle(.secondary).lineLimit(2)
                }.font(.caption)
                Text("连接会打开专用 Chrome 窗口。请保留窗口，在其中完成登录或验证；此窗口已静音。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 14) {
                metric("收到进房", model.received, "person.crop.circle.badge.plus")
                metric("已欢迎", model.spoken, "speaker.wave.2")
                metric("等待播报", model.pending, "list.bullet")
                metric("已跳过", model.skipped, "forward.end")
            }
            card("02  欢迎播报") {
                HStack(alignment: .top) {
                    Image(systemName: model.phase == "playing" ? "waveform" : "speaker.wave.2.circle")
                        .font(.system(size: 28)).foregroundStyle(accent).frame(width: 42)
                    VStack(alignment: .leading, spacing: 7) {
                        Text(model.paused ? "播报已暂停" : model.phase == "synthesizing" ? "正在合成声音…" : model.phase == "playing" ? "正在欢迎" : "准备好欢迎下一位朋友")
                            .font(.system(size: 17, weight: .medium))
                        Text(model.speaking.isEmpty ? model.settings.template.replacingOccurrences(of: "{name}", with: "小明") : model.speaking)
                            .foregroundStyle(.secondary).textSelection(.enabled)
                        Text(model.settings.mode == "system" ? "当前：系统声音，仅用于测试" : "当前：你的克隆声音 · 本地 Qwen3-TTS")
                            .font(.caption).foregroundStyle(accent)
                    }
                    Spacer()
                    Button(model.paused ? "恢复播报" : "停止播报") { model.send(model.paused ? "resume" : "stop") }
                        .tint(model.paused ? accent : .red).buttonStyle(.bordered).disabled(!model.ready)
                }
                Divider()
                HStack {
                    TextField("测试昵称", text: $testName).textFieldStyle(.roundedBorder).frame(maxWidth: 200)
                    Button("试听欢迎语") { model.action("preview", name: testName) }
                    Button("模拟进房") { model.action("simulate", name: testName) }
                    Spacer()
                    Button("设置我的声音 →") { tab = "voice" }.buttonStyle(.plain).foregroundStyle(accent)
                }.disabled(!model.ready || model.paused)
            }
            card("运行记录") {
                if model.entries.isEmpty { Text("连接或试听后，事件会显示在这里。").foregroundStyle(.secondary).font(.callout) }
                ForEach(model.entries.prefix(8)) { entry in
                    HStack(alignment: .top, spacing: 12) {
                        Text(entry.time, style: .time).monospacedDigit().foregroundStyle(.tertiary).frame(width: 75, alignment: .leading)
                        Circle().fill(entry.level == "error" ? .red : entry.level == "warning" ? .orange : accent.opacity(0.7)).frame(width: 5, height: 5).padding(.top, 5)
                        Text(entry.message).foregroundStyle(entry.level == "error" ? .red : .secondary).textSelection(.enabled)
                        Spacer(minLength: 0)
                    }.font(.caption)
                }
            }
        }
    }

    func metric(_ title: String, _ count: Int, _ icon: String) -> some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack { Text(title); Spacer(); Image(systemName: icon) }.font(.caption).foregroundStyle(.secondary)
            Text("\(count)").font(.system(size: 28, weight: .medium, design: .rounded)).monospacedDigit()
        }.padding(18).frame(maxWidth: .infinity).background(accent.opacity(0.045), in: RoundedRectangle(cornerRadius: 12))
    }

    var voice: some View {
        VStack(spacing: 20) {
            card("声音来源") {
                Picker("声音模式", selection: $model.settings.mode) {
                    Text("系统声音 · 测试链路").tag("system")
                    Text("我的克隆声音 · 本地生成").tag("clone")
                }.pickerStyle(.segmented)
                Text("克隆在这台 Mac 上运行。首次试听会下载模型，之后会保留本地缓存；声音相似度需要你试听确认。")
                    .font(.callout).foregroundStyle(.secondary)
            }
            card("01  导入你的原声") {
                HStack {
                    Image(systemName: "waveform.badge.mic").font(.title2).foregroundStyle(accent)
                    VStack(alignment: .leading, spacing: 5) {
                        Text(model.settings.reference_audio.isEmpty ? "尚未导入录音" : URL(fileURLWithPath: model.settings.reference_audio).lastPathComponent).lineLimit(1)
                        Text("WAV / AIFF · 3～30 秒 · 只有你说话，没有音乐").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("选择录音…") { model.chooseRecording() }
                }
                Text("推荐用平时直播的语气录制 10～20 秒。豆包 App 内的音色不能直接作为这里的模型导入。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            card("02  填写录音中说的话") {
                TextEditor(text: $model.settings.reference_text).font(.body).frame(height: 110)
                    .padding(8).background(.background, in: RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(.quaternary))
                Text("请逐字填写，与录音一致。这段文字只用于参考声音，不是欢迎语。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            card("03  试听并确认") {
                HStack {
                    TextField("测试昵称", text: $testName).textFieldStyle(.roundedBorder)
                    Button("保存并试听") { model.action("preview", name: testName) }
                        .buttonStyle(.borderedProminent).disabled(!model.ready || model.paused)
                    Button("停止") { model.send("stop") }.disabled(!model.ready)
                }
                if model.paused { Button("播报已暂停，点此恢复") { model.send("resume") } }
                Text(model.phase == "synthesizing" ? "正在准备或生成声音，首次使用可能需要几分钟。进度见工作台运行记录。" : "开播前先试听一次，让模型完成预热。停止播报会释放模型内存。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    var settings: some View {
        VStack(spacing: 20) {
            card("欢迎语与节奏") {
                TextField("欢迎{name}，欢迎来到直播间！", text: $model.settings.template).textFieldStyle(.roundedBorder)
                Text("{name} 会替换成昵称。积压时最多合并三人；表情、链接和长数字会清理。")
                    .font(.caption).foregroundStyle(.secondary)
                Stepper("两次播报之间至少间隔 \(model.settings.interval) 秒", value: $model.settings.interval, in: 0...120)
                Stepper("同一用户 \(model.settings.dedup_seconds / 60) 分钟内只欢迎一次", value: $model.settings.dedup_seconds, in: 60...3600, step: 60)
                Stepper("超过 \(model.settings.max_age) 秒的欢迎消息跳过", value: $model.settings.max_age, in: 5...120, step: 5)
                TextField("不播报的昵称关键词，用逗号分隔", text: $model.settings.blocked_words).textFieldStyle(.roundedBorder)
            }
            card("音频输出") {
                HStack {
                    Picker("输出到", selection: $model.settings.output_device) {
                        Text("系统默认输出").tag("")
                        ForEach(model.devices, id: \.self) { Text($0).tag($0) }
                        if !model.settings.output_device.isEmpty && !model.devices.contains(model.settings.output_device) {
                            Text(model.settings.output_device + "（已断开）").tag(model.settings.output_device)
                        }
                    }
                    Button { model.send("devices") } label: { Image(systemName: "arrow.clockwise") }
                }
                HStack { Text("音量"); Slider(value: $model.settings.volume, in: 0...1); Text("\(Int(model.settings.volume * 100))%").monospacedDigit().frame(width: 42) }
                Divider()
                Text("让直播间听见声音").fontWeight(.medium)
                Text("先用耳机试听。正式开播时，可以让开播软件采集本应用声音；或安装 BlackHole，把这里的输出设为 BlackHole，再在开播软件中添加同一设备作为音频输入。你的麦克风仍需保留为另一路输入。")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Text("避免同时采集系统声音和虚拟声卡，否则会重复播报。手机开播还需要声卡或其他音频回传方案。")
                    .font(.caption).foregroundStyle(.secondary)
                Link("打开 BlackHole 官方下载页 ↗", destination: URL(string: "https://existential.audio/blackhole/")!)
            }
            HStack {
                Text(model.saveMessage).font(.caption).foregroundStyle(accent)
                Spacer()
                Button("保存设置") { model.save() }.buttonStyle(.borderedProminent).disabled(!model.ready)
            }
        }
    }
}
