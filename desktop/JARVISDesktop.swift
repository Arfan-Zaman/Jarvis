// JARVIS Desktop: a floating orb that wakes on a double clap.
//
// Flow: double clap -> chime, listen -> words sent to the local JARVIS server
// for transcription -> if they contain "Jarvis", the rest is the request ->
// JARVIS answers and acts (through the server's normal, permission-checked
// chat) -> the reply is shown in a bubble and spoken.
//
// Everything stays on this Mac: the microphone is analysed here only to find
// claps; audio is recorded only after a double clap (or a click on the orb)
// and is sent only to the JARVIS server on 127.0.0.1.
//
// Build with:  python3 -m jarvis desktop build
// Test the clap detector on a WAV file:  JARVIS --test-clap file.wav

import AppKit
import AVFoundation

// MARK: - Settings (written into Info.plist by the build script)

enum Settings {
    static func value(_ key: String, _ fallback: String) -> String {
        Bundle.main.object(forInfoDictionaryKey: key) as? String ?? fallback
    }
    static var root: String { value("JARVISRoot", NSHomeDirectory() + "/JARVIS") }
    static var python: String { value("JARVISPython", "/usr/bin/python3") }
    static var server: URL { URL(string: value("JARVISServer", "http://127.0.0.1:8765"))! }
}

// MARK: - Clap detector (pure signal processing, testable from a file)

final class ClapDetector {
    let sampleRate: Double
    let frameSize: Int
    private var pending: [Float] = []
    private var floorLevel: Float = 0.003
    private var recent: [Float] = []          // RMS of the last frames, before the current one
    private var inClap = false
    private var clapStart = 0
    private var clapPeakRMS: Float = 0
    private var frame = 0
    private var claps: [Int] = []
    private var lastTrigger = -1_000_000
    var onClap: ((Double) -> Void)?
    var onDoubleClap: ((Double) -> Void)?
    var onDebug: ((String) -> Void)?   // why a loud sound was or was not taken as a clap

    // Tunables (frames are 10 ms). Tuned on real claps recorded by the MacBook Pro
    // microphone (2026-11-16): peak 0.09-0.30, 22-95x the room level, faded in 10-20 ms,
    // and duller than expected (zero-crossing rate only 0.04-0.10), so "brightness" is
    // used only to reject deep thuds such as a knock on a desk or door.
    let minPeak: Float = 0.06          // a clap is loud...
    let onsetRatio: Float = 12         // ...very sudden compared with the room...
    let minBrightness: Float = 0.004   // ...not a deep thud...
    let maxClapFrames = 6              // ...and short: faded within 60 ms
    let minGap = 12, maxGap = 70       // two claps 120-700 ms apart
    let cooldown = 150                 // 1.5 s before another trigger

    init(sampleRate: Double) {
        self.sampleRate = sampleRate
        frameSize = max(64, Int(sampleRate * 0.01))
    }

    func process(_ samples: [Float]) {
        pending.append(contentsOf: samples)
        var offset = 0
        while pending.count - offset >= frameSize {
            analyse(pending[offset..<(offset + frameSize)])
            offset += frameSize
        }
        pending.removeFirst(offset)
    }

    private func analyse(_ chunk: ArraySlice<Float>) {
        var sum: Float = 0, peak: Float = 0, crossings = 0, change: Float = 0
        var previous = chunk.first ?? 0
        for sample in chunk {
            sum += sample * sample
            peak = max(peak, abs(sample))
            if (sample >= 0) != (previous >= 0) { crossings += 1 }
            change += (sample - previous) * (sample - previous)
            previous = sample
        }
        let rms = (sum / Float(chunk.count)).squareRoot()
        let zcr = Float(crossings) / Float(chunk.count)
        let brightness = sum > 0 ? change / sum : 0   // high for crisp sounds, tiny for deep thuds
        let baseline = recent.isEmpty ? floorLevel : max(recent.reduce(0, +) / Float(recent.count), floorLevel)

        let time = Double(frame) * Double(frameSize) / sampleRate
        if !inClap && peak >= 0.04, let onDebug {
            var why: [String] = []
            if peak < minPeak { why.append("too quiet") }
            if rms < baseline * onsetRatio { why.append("not sudden enough") }
            if brightness < minBrightness { why.append("deep thud") }
            onDebug(String(format: "t=%.2f peak=%.3f rms=%.4f sudden=%.1fx zcr=%.2f bright=%.4f %@",
                           time, peak, rms, rms / max(baseline, 0.0001), zcr, brightness,
                           why.isEmpty ? "-> onset" : "rejected: " + why.joined(separator: ", ")))
        }
        if !inClap {
            if peak >= minPeak && rms >= baseline * onsetRatio && brightness >= minBrightness {
                inClap = true
                clapStart = frame
                clapPeakRMS = rms
            } else {
                floorLevel = max(0.0005, floorLevel * 0.995 + rms * 0.005)
            }
        } else {
            clapPeakRMS = max(clapPeakRMS, rms)
            let length = frame - clapStart
            if rms < clapPeakRMS * 0.25 {                // faded: it was short and sharp
                inClap = false
                onDebug?(String(format: "   faded after %d ms -> clap", length * 10))
                if length <= maxClapFrames { register(clapStart) } else { claps.removeAll() }
            } else if length > maxClapFrames {           // sustained: speech, music, a door...
                inClap = false
                onDebug?(String(format: "   still loud after %d ms -> not a clap", length * 10))
                claps.removeAll()
            }
        }
        if !inClap {
            recent.append(rms)
            if recent.count > 20 { recent.removeFirst() }
        }
        frame += 1
    }

    private func register(_ start: Int) {
        let seconds = Double(start) * Double(frameSize) / sampleRate
        onClap?(seconds)
        if let previous = claps.last { onDebug?(String(format: "   gap to previous clap: %d ms", (start - previous) * 10)) }
        claps = claps.filter { start - $0 <= maxGap }
        if let previous = claps.last, start - previous >= minGap, start - lastTrigger >= cooldown {
            lastTrigger = start
            claps.removeAll()
            onDoubleClap?(seconds)
            return
        }
        claps.append(start)
    }
}

// MARK: - Diagnostic log (data/logs/desktop.log)

enum DesktopLog {
    static let url = URL(fileURLWithPath: Settings.root + "/data/logs/desktop.log")
    static let queue = DispatchQueue(label: "jarvis.log")
    static func write(_ line: String) {
        let stamp = ISO8601DateFormatter().string(from: Date())
        queue.async {
            let text = "\(stamp) \(line)\n"
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            if let handle = try? FileHandle(forWritingTo: url) {
                handle.seekToEndOfFile(); handle.write(text.data(using: .utf8)!); try? handle.close()
            } else {
                try? text.data(using: .utf8)!.write(to: url)
            }
        }
    }
}

// MARK: - Recording until the speaker stops

final class UtteranceRecorder {
    let sampleRate: Double
    private(set) var samples: [Float] = []
    private var frames = 0, speechFrames = 0, silenceFrames = 0, started = false
    private let frameSize: Int
    private var pending: [Float] = []
    private var noise: Float
    enum Outcome { case listening, finished, nothingSaid }

    init(sampleRate: Double, noise: Float) {
        self.sampleRate = sampleRate
        self.noise = max(noise, 0.002)
        frameSize = max(64, Int(sampleRate * 0.01))
    }

    func add(_ chunk: [Float]) -> Outcome {
        samples.append(contentsOf: chunk)
        pending.append(contentsOf: chunk)
        var outcome = Outcome.listening
        while pending.count >= frameSize {
            let slice = pending.prefix(frameSize)
            pending.removeFirst(frameSize)
            let rms = (slice.reduce(0) { $0 + $1 * $1 } / Float(frameSize)).squareRoot()
            frames += 1
            if rms > max(noise * 4, 0.01) { speechFrames += 1; silenceFrames = 0 } else { silenceFrames += 1 }
            if speechFrames >= 5 { started = true }
            if started && silenceFrames >= 120 { outcome = .finished }           // 1.2 s of quiet
            if !started && frames >= 600 { outcome = .nothingSaid }              // 6 s without speech
            if frames >= 1500 { outcome = started ? .finished : .nothingSaid }   // 15 s at most
            if outcome != .listening { break }
        }
        return outcome
    }

    func wav() -> Data {
        var data = Data()
        let rate = UInt32(sampleRate), count = UInt32(samples.count)
        func append<T>(_ value: T) { withUnsafeBytes(of: value) { data.append(contentsOf: $0) } }
        data.append("RIFF".data(using: .ascii)!); append(UInt32(36 + count * 2).littleEndian)
        data.append("WAVEfmt ".data(using: .ascii)!); append(UInt32(16).littleEndian)
        append(UInt16(1).littleEndian); append(UInt16(1).littleEndian)
        append(rate.littleEndian); append((rate * 2).littleEndian)
        append(UInt16(2).littleEndian); append(UInt16(16).littleEndian)
        data.append("data".data(using: .ascii)!); append((count * 2).littleEndian)
        for sample in samples { append(Int16(max(-1, min(1, sample)) * 32767).littleEndian) }
        return data
    }
}

// MARK: - Talking to the JARVIS server

struct JarvisAPI {
    let base = Settings.server

    func isUp() async -> Bool {
        var request = URLRequest(url: base.appendingPathComponent("api/status"))
        request.timeoutInterval = 2
        return (try? await URLSession.shared.data(for: request)).map { ($0.1 as? HTTPURLResponse)?.statusCode == 200 } ?? false
    }

    private func post(_ path: String, body: Data, type: String, timeout: TimeInterval) async throws -> Data {
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue(type, forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = timeout
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode < 300 else {
            let message = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw NSError(domain: "JARVIS", code: 1, userInfo: [NSLocalizedDescriptionKey: message ?? "JARVIS returned an error"])
        }
        return data
    }

    func transcribe(_ wav: Data) async throws -> String {
        let data = try await post("api/voice/transcribe", body: wav, type: "audio/wav", timeout: 120)
        return ((try JSONSerialization.jsonObject(with: data) as? [String: Any])?["text"] as? String) ?? ""
    }

    func chat(_ message: String, conversation: Int?) async throws -> (reply: String, conversation: Int?) {
        var payload: [String: Any] = ["message": message]
        if let conversation { payload["conversation_id"] = conversation }
        let data = try await post("api/chat", body: try JSONSerialization.data(withJSONObject: payload),
                                  type: "application/json", timeout: 600)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let reply = (json?["reply"] as? [String: Any])?["content"] as? String ?? ""
        let id = (json?["conversation"] as? [String: Any])?["id"] as? Int
        return (reply, id)
    }

    func speech(_ text: String) async throws -> Data {
        try await post("api/voice/speak", body: try JSONSerialization.data(withJSONObject: ["text": text]),
                       type: "application/json", timeout: 60)
    }
}

final class ServerManager {
    private var process: Process?

    /// Make sure the JARVIS server is running; start it if needed.
    func ensureRunning(api: JarvisAPI) async -> Bool {
        if await api.isUp() { return true }
        let task = Process()
        task.executableURL = URL(fileURLWithPath: Settings.python)
        task.arguments = ["-m", "jarvis", "serve"]
        task.currentDirectoryURL = URL(fileURLWithPath: Settings.root)
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        task.environment = env
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice
        do { try task.run() } catch { return false }
        process = task
        for _ in 0..<60 {
            try? await Task.sleep(nanoseconds: 500_000_000)
            if await api.isUp() { return true }
        }
        return false
    }

    func stopIfStarted() {
        if let process, process.isRunning { process.terminate() }
    }
}

// MARK: - The orb

enum OrbState { case starting, idle, listening, thinking, speaking, muted, offline }

final class OrbView: NSView {
    private let ring = CAShapeLayer(), arc = CAShapeLayer(), core = CAShapeLayer(), glow = CALayer()
    private let label = CATextLayer()
    var onClick: (() -> Void)?
    var menuProvider: (() -> NSMenu)?

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        let bounds = CGRect(origin: .zero, size: frame.size)
        let centre = CGPoint(x: bounds.midX, y: bounds.midY)
        func circle(_ radius: CGFloat) -> CGPath {
            CGPath(ellipseIn: CGRect(x: centre.x - radius, y: centre.y - radius, width: radius * 2, height: radius * 2), transform: nil)
        }
        glow.frame = bounds.insetBy(dx: 14, dy: 14)
        glow.cornerRadius = glow.frame.width / 2
        glow.shadowOpacity = 0.9
        glow.shadowRadius = 18
        glow.shadowOffset = .zero
        glow.backgroundColor = NSColor(white: 0.05, alpha: 0.85).cgColor
        for (layer, radius, width) in [(ring, 46.0, 2.0), (arc, 38.0, 4.0)] {
            layer.frame = bounds
            layer.path = circle(radius)
            layer.fillColor = nil
            layer.lineWidth = width
        }
        ring.lineDashPattern = [3, 5]
        arc.strokeEnd = 0.7
        arc.lineCap = .round
        core.frame = bounds
        core.path = circle(10)
        label.string = "J.A.R.V.I.S."
        label.fontSize = 8
        label.alignmentMode = .center
        label.foregroundColor = NSColor(white: 0.9, alpha: 0.9).cgColor
        label.frame = CGRect(x: 0, y: centre.y - 26, width: bounds.width, height: 12)
        label.contentsScale = NSScreen.main?.backingScaleFactor ?? 2
        [glow, ring, arc, core, label].forEach { layer?.addSublayer($0) }
        set(.starting)
    }
    required init?(coder: NSCoder) { fatalError() }

    func set(_ state: OrbState) {
        let violet = NSColor(calibratedRed: 0.55, green: 0.36, blue: 0.96, alpha: 1)
        let pink = NSColor(calibratedRed: 1, green: 0.24, blue: 0.6, alpha: 1)
        let cyan = NSColor(calibratedRed: 0.35, green: 0.9, blue: 0.95, alpha: 1)
        let grey = NSColor(white: 0.45, alpha: 1)
        let (colour, spin, pulse): (NSColor, Double, Double) = {
            switch state {
            case .starting: return (grey, 6, 0)
            case .idle: return (violet, 14, 3.5)
            case .listening: return (pink, 3, 0.8)
            case .thinking: return (violet, 1.2, 0)
            case .speaking: return (cyan, 4, 0.5)
            case .muted: return (grey, 0, 0)
            case .offline: return (NSColor.systemRed, 0, 0)
            }
        }()
        CATransaction.begin()
        for layer in [ring, arc] { layer.strokeColor = colour.cgColor }
        core.fillColor = colour.withAlphaComponent(0.9).cgColor
        glow.shadowColor = colour.cgColor
        CATransaction.commit()
        arc.removeAllAnimations(); core.removeAllAnimations()
        if spin > 0 {
            let rotate = CABasicAnimation(keyPath: "transform.rotation.z")
            rotate.fromValue = 0; rotate.toValue = -Double.pi * 2
            rotate.duration = spin; rotate.repeatCount = .infinity
            arc.add(rotate, forKey: "spin")
        }
        if pulse > 0 {
            let breathe = CABasicAnimation(keyPath: "opacity")
            breathe.fromValue = 1; breathe.toValue = 0.35
            breathe.duration = pulse; breathe.autoreverses = true; breathe.repeatCount = .infinity
            core.add(breathe, forKey: "pulse")
        }
    }

    override func mouseDown(with event: NSEvent) {
        if event.clickCount == 1 { window?.performDrag(with: event) }
    }
    override func mouseUp(with event: NSEvent) {
        if event.clickCount == 1, NSEvent.modifierFlags.isEmpty { onClick?() }
    }
    override func menu(for event: NSEvent) -> NSMenu? { menuProvider?() }
}

// MARK: - The app

final class AppDelegate: NSObject, NSApplicationDelegate, AVAudioPlayerDelegate {
    private var panel: NSPanel!
    private var orb: OrbView!
    private var bubble: NSTextField!
    private var bubbleBox: NSVisualEffectView!
    private let engine = AVAudioEngine()
    private let audioQueue = DispatchQueue(label: "jarvis.audio")
    private var detector: ClapDetector?
    private var recorder: UtteranceRecorder?
    private var player: AVAudioPlayer?
    private let api = JarvisAPI()
    private let server = ServerManager()
    private var conversation: Int?
    private var state: OrbState = .starting
    private var muted = false
    private var followUp = false         // "Jarvis" alone: listen once more for the request
    private var hideBubble: DispatchWorkItem?

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildPanel()
        say("Starting up…", speak: false)
        Task { @MainActor in
            let up = await server.ensureRunning(api: api)
            if !up { setState(.offline); say("I couldn't start the JARVIS server. Open the JARVIS folder and run it once by hand to see why.", speak: false); return }
            await startMicrophone()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        engine.stop()
        server.stopIfStarted()
    }

    // --- window ---
    private func buildPanel() {
        let size = NSSize(width: 360, height: 120)
        let saved = UserDefaults.standard.string(forKey: "orbOrigin").map(NSPointFromString)
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let origin = saved ?? NSPoint(x: screen.maxX - size.width - 24, y: screen.minY + 24)
        panel = NSPanel(contentRect: NSRect(origin: origin, size: size),
                        styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.isMovableByWindowBackground = true
        NotificationCenter.default.addObserver(forName: NSWindow.didMoveNotification, object: panel, queue: .main) { [weak self] _ in
            if let frame = self?.panel.frame { UserDefaults.standard.set(NSStringFromPoint(frame.origin), forKey: "orbOrigin") }
        }

        let content = NSView(frame: NSRect(origin: .zero, size: size))
        orb = OrbView(frame: NSRect(x: size.width - 120, y: 0, width: 120, height: 120))
        orb.onClick = { [weak self] in self?.manualWake() }
        orb.menuProvider = { [weak self] in self?.menu() ?? NSMenu() }
        bubbleBox = NSVisualEffectView(frame: NSRect(x: 0, y: 14, width: size.width - 126, height: 92))
        bubbleBox.material = .hudWindow
        bubbleBox.blendingMode = .behindWindow
        bubbleBox.state = .active
        bubbleBox.wantsLayer = true
        bubbleBox.layer?.cornerRadius = 14
        bubble = NSTextField(wrappingLabelWithString: "")
        bubble.frame = bubbleBox.bounds.insetBy(dx: 12, dy: 8)
        bubble.textColor = .white
        bubble.font = .systemFont(ofSize: 12)
        bubble.maximumNumberOfLines = 6
        bubbleBox.addSubview(bubble)
        bubbleBox.isHidden = true
        content.addSubview(bubbleBox)
        content.addSubview(orb)
        panel.contentView = content
        panel.orderFrontRegardless()
    }

    private func menu() -> NSMenu {
        let menu = NSMenu()
        menu.addItem(withTitle: "Open JARVIS", action: #selector(openJarvis), keyEquivalent: "").target = self
        let listen = menu.addItem(withTitle: muted ? "Start listening for claps" : "Stop listening for claps",
                                  action: #selector(toggleMute), keyEquivalent: "")
        listen.target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit JARVIS Desktop", action: #selector(quit), keyEquivalent: "").target = self
        return menu
    }
    @objc private func openJarvis() { NSWorkspace.shared.open(Settings.server) }
    @objc private func toggleMute() {
        muted.toggle()
        if muted { engine.stop(); setState(.muted); say("Clap listening is off. Click me to talk.", speak: false) }
        else { Task { @MainActor in await startMicrophone() } }
    }
    @objc private func quit() { NSApp.terminate(nil) }

    private func setState(_ new: OrbState) {
        state = new
        orb.set(new)
    }

    private func say(_ text: String, speak: Bool, linger: Double = 14) {
        hideBubble?.cancel()
        bubble.stringValue = text
        bubbleBox.isHidden = text.isEmpty
        let work = DispatchWorkItem { [weak self] in self?.bubbleBox.isHidden = true }
        hideBubble = work
        DispatchQueue.main.asyncAfter(deadline: .now() + linger, execute: work)
        if speak { Task { @MainActor in await self.speak(text) } }
    }

    // --- microphone ---
    @MainActor private func startMicrophone() async {
        let allowed = await withCheckedContinuation { (done: CheckedContinuation<Bool, Never>) in
            AVCaptureDevice.requestAccess(for: .audio) { done.resume(returning: $0) }
        }
        DesktopLog.write("microphone permission: \(allowed ? "allowed" : "DENIED")")
        guard allowed else {
            setState(.muted)
            say("I need microphone access to hear your claps. Allow JARVIS in System Settings, Privacy & Security, Microphone. You can still click me.", speak: false, linger: 30)
            return
        }
        let input = engine.inputNode
        let format = input.inputFormat(forBus: 0)
        let detector = ClapDetector(sampleRate: format.sampleRate)
        detector.onDoubleClap = { [weak self] _ in
            DesktopLog.write("DOUBLE CLAP -> waking")
            DispatchQueue.main.async { self?.wake() }
        }
        detector.onDebug = { DesktopLog.write($0) }
        DesktopLog.write(String(format: "microphone started: %.0f Hz, %d channel(s)", format.sampleRate, format.channelCount))
        self.detector = detector
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            guard let channel = buffer.floatChannelData?[0] else { return }
            let samples = Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
            self?.audioQueue.async { self?.handle(samples) }
        }
        do {
            try engine.start()
            setState(.idle)
            say("Ready. Clap twice, then say “Jarvis…” and your request.", speak: false, linger: 8)
        } catch {
            setState(.offline)
            say("The microphone could not start: \(error.localizedDescription)", speak: false)
        }
    }

    /// Runs on the audio queue.
    private func handle(_ samples: [Float]) {
        if let recorder {
            switch recorder.add(samples) {
            case .listening: break
            case .finished:
                self.recorder = nil
                let wav = recorder.wav()
                DispatchQueue.main.async { self.heard(wav) }
            case .nothingSaid:
                self.recorder = nil
                DispatchQueue.main.async { self.setState(.idle); self.say("I'll be here.", speak: false, linger: 4) }
            }
            return
        }
        let current = DispatchQueue.main.sync { state }
        if current == .idle { detector?.process(samples) }
    }

    // --- the conversation loop ---
    private func wake() {
        guard state == .idle || state == .muted || state == .offline else { return }
        followUp = false
        listen()
    }
    private func manualWake() {
        if state == .speaking { player?.stop(); finishSpeaking(); return }
        followUp = true                       // a click needs no "Jarvis"
        listen()
    }
    private func listen() {
        player?.stop()
        NSSound(named: "Tink")?.play()
        setState(.listening)
        say(followUp ? "Listening…" : "Listening… say “Jarvis” and your request.", speak: false, linger: 15)
        let rate = engine.inputNode.inputFormat(forBus: 0).sampleRate
        if !engine.isRunning { try? engine.start() }
        audioQueue.async { self.recorder = UtteranceRecorder(sampleRate: rate, noise: 0.004) }
    }

    private func heard(_ wav: Data) {
        setState(.thinking)
        say("…", speak: false)
        Task { @MainActor in
            do {
                let text = try await api.transcribe(wav)
                DesktopLog.write("heard: \(text)")
                guard let request = request(from: text) else {
                    setState(.idle); say(text.isEmpty ? "I didn't catch that." : "I heard “\(text)”, but not my name.", speak: false, linger: 5)
                    return
                }
                if request.isEmpty {                          // just "Jarvis"
                    followUp = true
                    say("Yes, sir?", speak: true)
                    return
                }
                let lowered = request.lowercased()
                if ["go to sleep", "that's all", "that is all", "goodbye", "never mind"].contains(where: lowered.hasPrefix) {
                    say("Very good, sir. I shall be here.", speak: true)
                    followUp = false
                    return
                }
                say("“\(request)”", speak: false)
                let result = try await api.chat(request, conversation: conversation)
                conversation = result.conversation ?? conversation
                followUp = false
                say(result.reply, speak: true, linger: 25)
            } catch {
                setState(.idle)
                say("Something went wrong: \(error.localizedDescription)", speak: false)
            }
        }
    }

    /// The request after "Jarvis", "" if only the name was said, nil if the name was not said.
    private func request(from text: String) -> String? {
        let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if followUp { return cleaned.isEmpty ? nil : cleaned }
        let pattern = #"(?i)\b(jarvis|jarvas|jervis|javis|jarviss)\b[\s,.!?:;-]*"#
        guard let range = cleaned.range(of: pattern, options: .regularExpression) else { return nil }
        return String(cleaned[range.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
    }

    @MainActor private func speak(_ text: String) async {
        do {
            setState(.speaking)
            let audio = try await api.speech(text)
            let player = try AVAudioPlayer(data: audio)
            player.delegate = self
            self.player = player
            player.play()
        } catch {
            finishSpeaking()
        }
    }

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        DispatchQueue.main.async { self.finishSpeaking() }
    }

    private func finishSpeaking() {
        if followUp { listen(); return }        // after "Yes, sir?" listen for the request
        setState(muted ? .muted : .idle)
    }
}

// MARK: - Entry point

let arguments = CommandLine.arguments
if arguments.count >= 3, arguments[1] == "--test-clap" {
    // Analyse a recording and report detections (used by the automated tests).
    let file = try AVAudioFile(forReading: URL(fileURLWithPath: arguments[2]))
    let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: file.fileFormat.sampleRate, channels: 1, interleaved: false)!
    let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(file.length))!
    try file.read(into: buffer)
    let detector = ClapDetector(sampleRate: format.sampleRate)
    var clapCount = 0
    detector.onClap = { _ in clapCount += 1 }
    detector.onDoubleClap = { print(String(format: "DOUBLE_CLAP %.2f", $0)) }
    if arguments.contains("--verbose") { detector.onDebug = { print($0) } }
    let samples = Array(UnsafeBufferPointer(start: buffer.floatChannelData![0], count: Int(buffer.frameLength)))
    stride(from: 0, to: samples.count, by: 1024).forEach { detector.process(Array(samples[$0..<min($0 + 1024, samples.count)])) }
    print("CLAPS \(clapCount)")
    exit(0)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
