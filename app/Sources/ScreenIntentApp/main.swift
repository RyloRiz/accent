import AppKit
import AVFoundation
import Carbon
import Foundation

struct Paths {
    let appDir: URL
    let repoDir: URL
    let runtimeDir: URL
    let screenshotURL: URL
    let speechInputURL: URL
    let speechOutputURL: URL
    let appLogURL: URL
    let runEnvURL: URL
    let runLogURL: URL
    let completeRunURL: URL
    let pythonURL: URL
    let conflictResolutionURL: URL
    let finalActionButtonsURL: URL
    let inputImageURL: URL
    let detectionsURL: URL

    static func detect() -> Paths {
        let current = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let appDir = current.lastPathComponent == "app" ? current : current.appendingPathComponent("app")
        let repoDir = appDir.deletingLastPathComponent()
        let runtimeDir = appDir.appendingPathComponent("runtime")
        let outputDir = repoDir.appendingPathComponent("test_outputs")

        return Paths(
            appDir: appDir,
            repoDir: repoDir,
            runtimeDir: runtimeDir,
            screenshotURL: runtimeDir.appendingPathComponent("screen_intent_input.png"),
            speechInputURL: runtimeDir.appendingPathComponent("speech_input.m4a"),
            speechOutputURL: runtimeDir.appendingPathComponent("speech_output.mp3"),
            appLogURL: runtimeDir.appendingPathComponent("app.log"),
            runEnvURL: runtimeDir.appendingPathComponent("run.env"),
            runLogURL: runtimeDir.appendingPathComponent("complete_run.log"),
            completeRunURL: repoDir.appendingPathComponent("complete_run.py"),
            pythonURL: repoDir.appendingPathComponent("env/bin/python3"),
            conflictResolutionURL: outputDir.appendingPathComponent("conflict_resolution.json"),
            finalActionButtonsURL: outputDir.appendingPathComponent("final_action_buttons.json"),
            inputImageURL: outputDir.appendingPathComponent("input_image.png"),
            detectionsURL: outputDir.appendingPathComponent("detections.json")
        )
    }
}

struct ConflictResolution: Decodable {
    let user_intent: String
    let plaintext_response: String
    let selected_element_id: String
    let selected_semantic: String
    let direction_for_user: String
}

struct ActionButton: Decodable {
    let semantic: String
    let box: PixelBox
}

struct PixelBox: Decodable {
    let x1: Double
    let y1: Double
    let x2: Double
    let y2: Double
}

struct DetectionItem: Decodable {
    let element_id: String
    let box: [Double]
    let confidence: Double?
}

final class AppLogger {
    static let shared = AppLogger()
    private var logURL: URL?

    func configure(_ url: URL) {
        logURL = url
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        log("App logger ready")
    }

    func log(_ message: String) {
        let line = "[\(Self.timestamp())] \(message)\n"
        print(line, terminator: "")
        guard let logURL else { return }
        if let data = line.data(using: .utf8) {
            if FileManager.default.fileExists(atPath: logURL.path),
               let handle = try? FileHandle(forWritingTo: logURL) {
                handle.seekToEndOfFile()
                handle.write(data)
                try? handle.close()
            } else {
                try? data.write(to: logURL)
            }
        }
    }

    private static func timestamp() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        return formatter.string(from: Date())
    }
}

final class HotKeyManager {
    private var hotKeyRef: EventHotKeyRef?
    private var eventHandler: EventHandlerRef?
    private let action: () -> Void

    init(action: @escaping () -> Void) {
        self.action = action
        register()
    }

    deinit {
        if let hotKeyRef {
            UnregisterEventHotKey(hotKeyRef)
        }
        if let eventHandler {
            RemoveEventHandler(eventHandler)
        }
    }

    private func register() {
        let hotKeyID = EventHotKeyID(signature: OSType(0x53494149), id: 1)
        RegisterEventHotKey(
            UInt32(kVK_Space),
            UInt32(cmdKey | shiftKey),
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &hotKeyRef
        )

        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(
            GetApplicationEventTarget(),
            { _, _, userData in
                guard let userData else { return noErr }
                let manager = Unmanaged<HotKeyManager>.fromOpaque(userData).takeUnretainedValue()
                manager.action()
                return noErr
            },
            1,
            &eventType,
            Unmanaged.passUnretained(self).toOpaque(),
            &eventHandler
        )
    }
}

final class PillButton: NSButton {
    private let fillColor: NSColor
    private let activeFillColor: NSColor
    private let foregroundColor: NSColor

    init(title: String, symbolName: String? = nil, fillColor: NSColor, activeFillColor: NSColor? = nil, foregroundColor: NSColor = .white) {
        self.fillColor = fillColor
        self.activeFillColor = activeFillColor ?? fillColor
        self.foregroundColor = foregroundColor
        super.init(frame: .zero)
        self.title = title
        imagePosition = title.isEmpty ? .imageOnly : .imageLeading
        imageScaling = .scaleProportionallyDown
        alignment = .center
        if let symbolName {
            image = NSImage(systemSymbolName: symbolName, accessibilityDescription: title.isEmpty ? symbolName : title)
        }
        isBordered = false
        wantsLayer = true
        layer?.cornerRadius = 15
        layer?.backgroundColor = fillColor.cgColor
        font = .systemFont(ofSize: 15, weight: .semibold)
        contentTintColor = foregroundColor
        attributedTitle = NSAttributedString(
            string: title,
            attributes: [
                .foregroundColor: foregroundColor,
                .font: font as Any
            ]
        )
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func setActive(_ isActive: Bool) {
        layer?.backgroundColor = (isActive ? activeFillColor : fillColor).cgColor
    }
}

struct EnvConfig {
    let values: [String: String]

    static func load(paths: Paths) -> EnvConfig {
        var values = ProcessInfo.processInfo.environment
        let envURL = paths.repoDir.appendingPathComponent(".env")
        if let text = try? String(contentsOf: envURL, encoding: .utf8) {
            for line in text.split(separator: "\n", omittingEmptySubsequences: false) {
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmed.isEmpty, !trimmed.hasPrefix("#"), let equals = trimmed.firstIndex(of: "=") else {
                    continue
                }
                let key = trimmed[..<equals].trimmingCharacters(in: .whitespacesAndNewlines)
                var value = trimmed[trimmed.index(after: equals)...].trimmingCharacters(in: .whitespacesAndNewlines)
                if value.count >= 2, let first = value.first, let last = value.last, (first == "'" || first == "\""), first == last {
                    value.removeFirst()
                    value.removeLast()
                }
                values[key] = value
            }
        }
        return EnvConfig(values: values)
    }

    func string(_ key: String, default defaultValue: String = "") -> String {
        values[key] ?? defaultValue
    }
}

final class ElevenLabsClient {
    private let paths: Paths
    private var player: AVAudioPlayer?
    private var speechToken = UUID()

    init(paths: Paths) {
        self.paths = paths
    }

    func transcribe(audioURL: URL, completion: @escaping (Result<String, Error>) -> Void) {
        let config = EnvConfig.load(paths: paths)
        let apiKey = config.string("ELEVENLABS_API_KEY")
        guard !apiKey.isEmpty else {
            AppLogger.shared.log("ElevenLabs STT skipped: missing ELEVENLABS_API_KEY")
            completion(.failure(messageError("Set ELEVENLABS_API_KEY in .env to use the microphone.")))
            return
        }

        guard let url = URL(string: "https://api.elevenlabs.io/v1/speech-to-text") else {
            completion(.failure(messageError("Invalid ElevenLabs STT URL.")))
            return
        }

        do {
            let audioData = try Data(contentsOf: audioURL)
            AppLogger.shared.log("ElevenLabs STT upload starting, bytes=\(audioData.count), model=\(config.string("ELEVENLABS_STT_MODEL", default: "scribe_v2"))")
            let boundary = "Boundary-\(UUID().uuidString)"
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.timeoutInterval = 90
            request.setValue(apiKey, forHTTPHeaderField: "xi-api-key")
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            request.httpBody = multipartBody(
                boundary: boundary,
                fields: ["model_id": config.string("ELEVENLABS_STT_MODEL", default: "scribe_v2")],
                fileField: "file",
                fileName: "speech_input.m4a",
                mimeType: "audio/mp4",
                fileData: audioData
            )

            URLSession.shared.dataTask(with: request) { data, response, error in
                if let error {
                    completion(.failure(error))
                    return
                }
                guard let http = response as? HTTPURLResponse else {
                    completion(.failure(self.messageError("ElevenLabs STT returned no HTTP response.")))
                    return
                }
                guard (200..<300).contains(http.statusCode), let data else {
                    let body = data.flatMap { String(data: $0, encoding: .utf8) } ?? ""
                    AppLogger.shared.log("ElevenLabs STT failed: status=\(http.statusCode), body=\(body.prefix(500))")
                    completion(.failure(self.messageError("ElevenLabs STT failed with \(http.statusCode): \(body)")))
                    return
                }
                do {
                    let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
                    let text = (object?["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !text.isEmpty else {
                        AppLogger.shared.log("ElevenLabs STT returned empty transcript")
                        completion(.failure(self.messageError("ElevenLabs returned an empty transcript.")))
                        return
                    }
                    AppLogger.shared.log("ElevenLabs STT transcript: \(text)")
                    completion(.success(text))
                } catch {
                    AppLogger.shared.log("ElevenLabs STT parse failed: \(error.localizedDescription)")
                    completion(.failure(error))
                }
            }.resume()
        } catch {
            AppLogger.shared.log("ElevenLabs STT audio read failed: \(error.localizedDescription)")
            completion(.failure(error))
        }
    }

    func speak(_ text: String, completion: ((Result<Void, Error>) -> Void)? = nil) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let token = UUID()
        speechToken = token

        let config = EnvConfig.load(paths: paths)
        let apiKey = config.string("ELEVENLABS_API_KEY")
        guard !apiKey.isEmpty else {
            AppLogger.shared.log("ElevenLabs TTS skipped: missing ELEVENLABS_API_KEY")
            completion?(.failure(messageError("Set ELEVENLABS_API_KEY in .env to use ElevenLabs TTS.")))
            return
        }

        let voiceID = config.string("ELEVENLABS_VOICE_ID", default: "JBFqnCBsd6RMkjVDRZzb")
        let outputFormat = config.string("ELEVENLABS_TTS_OUTPUT_FORMAT", default: "mp3_44100_128")
        guard let url = URL(string: "https://api.elevenlabs.io/v1/text-to-speech/\(voiceID)?output_format=\(outputFormat)") else {
            completion?(.failure(messageError("Invalid ElevenLabs TTS URL.")))
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 90
        request.setValue(apiKey, forHTTPHeaderField: "xi-api-key")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let payload: [String: Any] = [
            "text": text,
            "model_id": config.string("ELEVENLABS_TTS_MODEL", default: "eleven_multilingual_v2")
        ]

        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        } catch {
            completion?(.failure(error))
            return
        }

        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error {
                completion?(.failure(error))
                return
            }
            guard let http = response as? HTTPURLResponse else {
                completion?(.failure(self.messageError("ElevenLabs TTS returned no HTTP response.")))
                return
            }
            guard (200..<300).contains(http.statusCode), let data else {
                let body = data.flatMap { String(data: $0, encoding: .utf8) } ?? ""
                AppLogger.shared.log("ElevenLabs TTS failed: status=\(http.statusCode), body=\(body.prefix(500))")
                completion?(.failure(self.messageError("ElevenLabs TTS failed with \(http.statusCode): \(body)")))
                return
            }
            do {
                try data.write(to: self.paths.speechOutputURL, options: .atomic)
                DispatchQueue.main.async {
                    guard self.speechToken == token else { return }
                    do {
                        let player = try AVAudioPlayer(data: data)
                        self.player = player
                        player.prepareToPlay()
                        player.play()
                        AppLogger.shared.log("ElevenLabs TTS playback started, bytes=\(data.count)")
                        completion?(.success(()))
                    } catch {
                        AppLogger.shared.log("ElevenLabs TTS playback failed: \(error.localizedDescription)")
                        completion?(.failure(error))
                    }
                }
            } catch {
                AppLogger.shared.log("ElevenLabs TTS write failed: \(error.localizedDescription)")
                completion?(.failure(error))
            }
        }.resume()
    }

    func stopSpeaking() {
        speechToken = UUID()
        player?.stop()
        player = nil
    }

    private func multipartBody(
        boundary: String,
        fields: [String: String],
        fileField: String,
        fileName: String,
        mimeType: String,
        fileData: Data
    ) -> Data {
        var body = Data()
        for (key, value) in fields {
            body.append("--\(boundary)\r\n")
            body.append("Content-Disposition: form-data; name=\"\(key)\"\r\n\r\n")
            body.append("\(value)\r\n")
        }
        body.append("--\(boundary)\r\n")
        body.append("Content-Disposition: form-data; name=\"\(fileField)\"; filename=\"\(fileName)\"\r\n")
        body.append("Content-Type: \(mimeType)\r\n\r\n")
        body.append(fileData)
        body.append("\r\n--\(boundary)--\r\n")
        return body
    }

    private func messageError(_ message: String) -> NSError {
        NSError(domain: "ScreenIntentApp", code: 10, userInfo: [NSLocalizedDescriptionKey: message])
    }
}

extension Data {
    mutating func append(_ string: String) {
        append(Data(string.utf8))
    }
}

final class ElevenLabsMicController: NSObject {
    private let paths: Paths
    private let client: ElevenLabsClient
    private let audioEngine = AVAudioEngine()
    private var webSocket: URLSessionWebSocketTask?
    private var meterTimer: Timer?
    private var maxRecordingTimer: Timer?
    private var silenceStartedAt: Date?
    private var heardSpeech = false
    private var transcriptionToken = UUID()
    private var transcriptText = ""
    private var committedTranscriptText = ""
    private var lastPower: Float = -120
    private var sampleRate = 44_100
    private var audioFormatID = "pcm_44100"
    private var didRequestStop = false

    var onText: ((String) -> Void)?
    var onListeningChanged: ((Bool) -> Void)?
    var onTranscribingChanged: ((Bool) -> Void)?
    var onFinished: ((String) -> Void)?
    var onError: ((String) -> Void)?

    var isListening: Bool {
        audioEngine.isRunning
    }

    init(paths: Paths, client: ElevenLabsClient) {
        self.paths = paths
        self.client = client
        super.init()
    }

    func toggle() {
        isListening ? stopAndTranscribe() : startRecording()
    }

    func startListening() {
        guard !isListening else { return }
        startRecording()
    }

    func cancel() {
        didRequestStop = true
        transcriptionToken = UUID()
        meterTimer?.invalidate()
        meterTimer = nil
        maxRecordingTimer?.invalidate()
        maxRecordingTimer = nil
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        onListeningChanged?(false)
        AppLogger.shared.log("Mic cancelled")
    }

    private func startRecording() {
        requestMicPermission { [weak self] granted in
            DispatchQueue.main.async {
                guard let self else { return }
                guard granted else {
                    AppLogger.shared.log("Mic permission denied")
                    self.onError?("Microphone permission was denied.")
                    return
                }
                self.beginRealtimeTranscription()
            }
        }
    }

    private func requestMicPermission(_ completion: @escaping (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            AppLogger.shared.log("Mic permission already authorized")
            completion(true)
        case .notDetermined:
            AppLogger.shared.log("Requesting mic permission")
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                completion(granted)
            }
        default:
            AppLogger.shared.log("Mic permission unavailable: \(AVCaptureDevice.authorizationStatus(for: .audio).rawValue)")
            completion(false)
        }
    }

    private func beginRealtimeTranscription() {
        cancel()
        didRequestStop = false
        heardSpeech = false
        silenceStartedAt = nil
        transcriptText = ""
        committedTranscriptText = ""
        transcriptionToken = UUID()

        do {
            try FileManager.default.createDirectory(at: paths.runtimeDir, withIntermediateDirectories: true)
            try startAudioEngine()
            try startRealtimeSocket()
            onListeningChanged?(true)
            AppLogger.shared.log("Realtime mic streaming started, sampleRate=\(sampleRate), audioFormat=\(audioFormatID)")
            startMetering()
            startMaxRecordingTimer()
        } catch {
            AppLogger.shared.log("Realtime mic failed: \(error.localizedDescription)")
            onError?("Could not start realtime transcription: \(error.localizedDescription)")
            cancel()
        }
    }

    private func startRealtimeSocket() throws {
        let config = EnvConfig.load(paths: paths)
        let apiKey = config.string("ELEVENLABS_API_KEY")
        guard !apiKey.isEmpty else {
            throw messageError("Set ELEVENLABS_API_KEY in .env to use the microphone.")
        }

        let model = config.string("ELEVENLABS_REALTIME_STT_MODEL", default: "scribe_v2_realtime")
        var components = URLComponents(string: "wss://api.elevenlabs.io/v1/speech-to-text/realtime")
        components?.queryItems = [
            URLQueryItem(name: "model_id", value: model),
            URLQueryItem(name: "audio_format", value: audioFormatID),
            URLQueryItem(name: "commit_strategy", value: "manual"),
            URLQueryItem(name: "include_language_detection", value: "true")
        ]
        let languageCode = config.string("ELEVENLABS_STT_LANGUAGE_CODE")
        if !languageCode.isEmpty {
            components?.queryItems?.append(URLQueryItem(name: "language_code", value: languageCode))
        }
        guard let url = components?.url else {
            throw messageError("Invalid ElevenLabs realtime STT URL.")
        }

        var request = URLRequest(url: url)
        request.setValue(apiKey, forHTTPHeaderField: "xi-api-key")
        let socket = URLSession.shared.webSocketTask(with: request)
        webSocket = socket
        socket.resume()
        AppLogger.shared.log("ElevenLabs realtime socket opened with model=\(model), audioFormat=\(audioFormatID)")
        receiveRealtimeMessages(token: transcriptionToken)
    }

    private func startAudioEngine() throws {
        let input = audioEngine.inputNode
        let format = input.outputFormat(forBus: 0)
        sampleRate = supportedRealtimeSampleRate(Int(format.sampleRate))
        audioFormatID = "pcm_\(sampleRate)"
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
            guard let self else { return }
            let audioData = self.pcm16Data(from: buffer)
            guard !audioData.isEmpty else { return }
            let rms = self.rmsPower(from: buffer)
            DispatchQueue.main.async {
                self.lastPower = rms
            }
            self.sendAudioChunk(audioData, commit: false)
        }

        audioEngine.prepare()
        try audioEngine.start()
    }

    private func supportedRealtimeSampleRate(_ nativeSampleRate: Int) -> Int {
        let supported = [8000, 16000, 22050, 24000, 44100, 48000]
        return supported.min(by: { abs($0 - nativeSampleRate) < abs($1 - nativeSampleRate) }) ?? 16000
    }

    private func receiveRealtimeMessages(token: UUID) {
        webSocket?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let message):
                guard token == self.transcriptionToken else { return }
                self.handleRealtimeMessage(message)
                self.receiveRealtimeMessages(token: token)
            case .failure(let error):
                DispatchQueue.main.async {
                    guard token == self.transcriptionToken else { return }
                    if !self.didRequestStop {
                        AppLogger.shared.log("ElevenLabs realtime receive failed: \(error.localizedDescription)")
                        self.onError?("Realtime transcription failed: \(error.localizedDescription)")
                        self.cancel()
                    }
                }
            }
        }
    }

    private func handleRealtimeMessage(_ message: URLSessionWebSocketTask.Message) {
        let text: String?
        switch message {
        case .string(let value):
            text = value
        case .data(let data):
            text = String(data: data, encoding: .utf8)
        @unknown default:
            text = nil
        }

        guard let text, let data = text.data(using: .utf8) else { return }
        do {
            guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            let messageType = object["message_type"] as? String ?? object["type"] as? String ?? ""
            if messageType.contains("error") {
                let message = object["message"] as? String ?? object["error"] as? String ?? text
                DispatchQueue.main.async {
                    AppLogger.shared.log("Realtime STT error event: \(message)")
                    self.onError?("ElevenLabs realtime error: \(message)")
                    self.cancel()
                }
                return
            }
            let partial = object["text"] as? String ?? object["transcript"] as? String ?? ""
            guard !partial.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
            DispatchQueue.main.async {
                if messageType.contains("committed") {
                    self.committedTranscriptText = self.appendTranscriptSegment(self.committedTranscriptText, partial)
                    self.transcriptText = self.committedTranscriptText
                } else {
                    self.transcriptText = self.appendTranscriptSegment(self.committedTranscriptText, partial)
                }
                self.onText?(self.transcriptText)
                if messageType.contains("partial") || messageType.contains("committed") {
                    AppLogger.shared.log("Realtime transcript \(messageType): \(self.transcriptText)")
                }
            }
        } catch {
            AppLogger.shared.log("Realtime message parse skipped: \(text.prefix(200))")
        }
    }

    private func appendTranscriptSegment(_ prefix: String, _ segment: String) -> String {
        let prefix = prefix.trimmingCharacters(in: .whitespacesAndNewlines)
        let segment = segment.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prefix.isEmpty else { return segment }
        guard !segment.isEmpty else { return prefix }
        if prefix.hasSuffix(segment) || prefix == segment {
            return prefix
        }
        return "\(prefix) \(segment)"
    }

    private func sendAudioChunk(_ data: Data, commit: Bool) {
        let payload: [String: Any] = [
            "message_type": "input_audio_chunk",
            "audio_base_64": data.base64EncodedString(),
            "commit": commit,
            "sample_rate": sampleRate
        ]
        guard
            let jsonData = try? JSONSerialization.data(withJSONObject: payload),
            let json = String(data: jsonData, encoding: .utf8)
        else {
            return
        }
        webSocket?.send(.string(json)) { error in
            if let error {
                AppLogger.shared.log("Realtime audio send failed: \(error.localizedDescription)")
            }
        }
    }

    private func pcm16Data(from buffer: AVAudioPCMBuffer) -> Data {
        guard let channelData = buffer.floatChannelData else { return Data() }
        let channels = Int(buffer.format.channelCount)
        let frames = Int(buffer.frameLength)
        var data = Data(capacity: frames * 2)
        for frame in 0..<frames {
            var sample: Float = 0
            for channel in 0..<channels {
                sample += channelData[channel][frame]
            }
            sample /= Float(max(channels, 1))
            let clamped = max(-1, min(1, sample))
            var intSample = Int16(clamped * Float(Int16.max)).littleEndian
            withUnsafeBytes(of: &intSample) { data.append(contentsOf: $0) }
        }
        return data
    }

    private func rmsPower(from buffer: AVAudioPCMBuffer) -> Float {
        guard let channelData = buffer.floatChannelData else { return -120 }
        let frames = Int(buffer.frameLength)
        guard frames > 0 else { return -120 }
        var sum: Float = 0
        for frame in 0..<frames {
            let value = channelData[0][frame]
            sum += value * value
        }
        let rms = sqrt(sum / Float(frames))
        return 20 * log10(max(rms, 0.000_001))
    }

    private func messageError(_ message: String) -> NSError {
        NSError(domain: "ScreenIntentApp", code: 11, userInfo: [NSLocalizedDescriptionKey: message])
    }

    private func finalizeRealtimeTranscript() {
        didRequestStop = true
        meterTimer?.invalidate()
        meterTimer = nil
        maxRecordingTimer?.invalidate()
        maxRecordingTimer = nil
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        sendAudioChunk(Data(), commit: true)
        webSocket?.cancel(with: .normalClosure, reason: nil)
        webSocket = nil
        onListeningChanged?(false)

        let text = transcriptText.trimmingCharacters(in: .whitespacesAndNewlines)
        let finalText = committedTranscriptText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? text
            : committedTranscriptText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !finalText.isEmpty else {
            onError?("I did not catch any words. Try speaking again or type your request.")
            AppLogger.shared.log("Realtime mic ended without transcript")
            return
        }
        AppLogger.shared.log("Realtime mic final text: \(finalText)")
        onFinished?(finalText)
    }

    /*
    private func beginRecording() {
        cancel()
        heardSpeech = false
        silenceStartedAt = nil

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44_100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]

        do {
            try FileManager.default.createDirectory(at: paths.runtimeDir, withIntermediateDirectories: true)
            let recorder = try AVAudioRecorder(url: paths.speechInputURL, settings: settings)
            recorder.delegate = self
            recorder.isMeteringEnabled = true
            let didRecord = recorder.record()
            guard didRecord else {
                onError?("Could not start microphone recording.")
                AppLogger.shared.log("AVAudioRecorder.record() returned false")
                return
            }
            self.recorder = recorder
            onListeningChanged?(true)
            AppLogger.shared.log("Mic recording started at \(paths.speechInputURL.path)")
            startMetering()
            startMaxRecordingTimer()
        } catch {
            AppLogger.shared.log("Mic recording failed: \(error.localizedDescription)")
            onError?("Could not start recording: \(error.localizedDescription)")
        }
    }
    */

    private func startMetering() {
        meterTimer?.invalidate()
        meterTimer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            guard let self, self.audioEngine.isRunning else { return }
            let power = self.lastPower
            if power > -50 {
                self.heardSpeech = true
                self.silenceStartedAt = nil
            } else {
                if self.silenceStartedAt == nil {
                    self.silenceStartedAt = Date()
                } else if Date().timeIntervalSince(self.silenceStartedAt ?? Date()) > 1.5, self.heardSpeech {
                    AppLogger.shared.log("Realtime mic auto-stop after silence, power=\(String(format: "%.1f", power))")
                    self.finalizeRealtimeTranscript()
                }
            }
        }
    }

    private func startMaxRecordingTimer() {
        maxRecordingTimer?.invalidate()
        maxRecordingTimer = Timer.scheduledTimer(withTimeInterval: 7.0, repeats: false) { [weak self] _ in
            guard let self, self.audioEngine.isRunning else { return }
            AppLogger.shared.log("Realtime mic auto-stop after max duration")
            self.finalizeRealtimeTranscript()
        }
    }

    private func stopAndTranscribe() {
        finalizeRealtimeTranscript()
    }
}

final class CommandBarWindow: NSPanel, NSTextFieldDelegate {
    private let textField = NSTextField()
    private let micButton = PillButton(
        title: "",
        symbolName: "mic.fill",
        fillColor: NSColor.white.withAlphaComponent(0.16),
        activeFillColor: NSColor.systemRed,
        foregroundColor: .white
    )
    private let goButton = PillButton(
        title: "Go",
        fillColor: NSColor.systemBlue,
        activeFillColor: NSColor.systemBlue
    )
    private let hintLabel = NSTextField(labelWithString: "Ask what you want to do")
    private var transcribing = false
    private let mic: ElevenLabsMicController
    var onSubmit: ((String) -> Void)?

    init(paths: Paths, elevenLabs: ElevenLabsClient) {
        mic = ElevenLabsMicController(paths: paths, client: elevenLabs)
        let screenFrame = NSScreen.main?.frame ?? .zero
        let size = NSSize(width: 720, height: 92)
        let origin = NSPoint(x: screenFrame.midX - size.width / 2, y: screenFrame.midY - size.height / 2)

        super.init(
            contentRect: NSRect(origin: origin, size: size),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )

        isFloatingPanel = true
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        backgroundColor = .clear
        isOpaque = false
        hasShadow = true

        let visual = NSVisualEffectView(frame: NSRect(origin: .zero, size: size))
        visual.material = .hudWindow
        visual.blendingMode = .behindWindow
        visual.state = .active
        visual.wantsLayer = true
        visual.layer?.cornerRadius = 22
        visual.layer?.masksToBounds = true
        contentView = visual

        hintLabel.textColor = .secondaryLabelColor
        hintLabel.font = .systemFont(ofSize: 13, weight: .medium)
        hintLabel.frame = NSRect(x: 26, y: 63, width: 430, height: 18)
        visual.addSubview(hintLabel)

        textField.placeholderString = "Why can't they hear me?"
        textField.font = .systemFont(ofSize: 22, weight: .regular)
        textField.isBordered = false
        textField.backgroundColor = .clear
        textField.focusRingType = .none
        textField.delegate = self
        textField.frame = NSRect(x: 26, y: 19, width: 520, height: 36)
        visual.addSubview(textField)

        micButton.target = self
        micButton.action = #selector(toggleMic)
        micButton.frame = NSRect(x: 560, y: 24, width: 42, height: 32)
        visual.addSubview(micButton)

        goButton.target = self
        goButton.action = #selector(submit)
        goButton.frame = NSRect(x: 614, y: 24, width: 78, height: 32)
        visual.addSubview(goButton)

        mic.onText = { [weak self] text in
            self?.textField.stringValue = text
        }
        mic.onListeningChanged = { [weak self] listening in
            self?.setListening(listening)
        }
        mic.onTranscribingChanged = { [weak self] transcribing in
            guard let self else { return }
            self.transcribing = transcribing
            self.hintLabel.stringValue = transcribing ? "Transcribing with ElevenLabs..." : "Ask what you want to do"
            self.micButton.isEnabled = !transcribing
            self.goButton.isEnabled = !transcribing
        }
        mic.onFinished = { [weak self] text in
            AppLogger.shared.log("Mic finished with text: \(text)")
            self?.textField.stringValue = text
            self?.submit()
        }
        mic.onError = { [weak self] message in
            AppLogger.shared.log("Mic error shown: \(message)")
            self?.hintLabel.stringValue = message
            self?.setListening(false)
        }
    }

    func show() {
        mic.cancel()
        textField.stringValue = ""
        hintLabel.stringValue = "Ask what you want to do"
        center()
        makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        textField.becomeFirstResponder()
        mic.startListening()
    }

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }

    func control(_ control: NSControl, textView: NSTextView, doCommandBy commandSelector: Selector) -> Bool {
        if commandSelector == #selector(NSResponder.insertNewline(_:)) {
            submit()
            return true
        }
        if commandSelector == #selector(NSResponder.cancelOperation(_:)) {
            mic.cancel()
            orderOut(nil)
            return true
        }
        return false
    }

    @objc private func toggleMic() {
        mic.toggle()
    }

    private func setListening(_ listening: Bool) {
        if !transcribing {
            hintLabel.stringValue = listening ? "Listening... click mic again to stop" : "Ask what you want to do"
        }
        micButton.setActive(listening)
        micButton.image = NSImage(
            systemSymbolName: listening ? "stop.fill" : "mic.fill",
            accessibilityDescription: listening ? "Stop listening" : "Start listening"
        )
    }

    @objc private func submit() {
        guard !transcribing else { return }
        mic.cancel()
        let intent = textField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !intent.isEmpty else { return }
        orderOut(nil)
        onSubmit?(intent)
    }
}

final class DetectiveBlobView: NSView {
    private var timer: Timer?
    private var startDate = Date()

    override var isFlipped: Bool { true }

    func startAnimation() {
        startDate = Date()
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60.0, repeats: true) { [weak self] _ in
            self?.needsDisplay = true
        }
    }

    func stopAnimation() {
        timer?.invalidate()
        timer = nil
    }

    override func draw(_ dirtyRect: NSRect) {
        let elapsed = CGFloat(Date().timeIntervalSince(startDate))
        let bounce = -5 + 5 * cos((elapsed / 2) * 2 * .pi)
        let side = min(bounds.width, bounds.height)

        NSGraphicsContext.saveGraphicsState()
        let transform = NSAffineTransform()
        transform.translateX(by: bounds.midX - side / 2, yBy: bounds.midY - side / 2 + bounce)
        transform.scale(by: side / 400)
        transform.concat()

        drawBlobBody()
        drawHat(elapsed: elapsed)
        drawCheeksAndFace(elapsed: elapsed)
        drawMagnifyingGlass(elapsed: elapsed)
        drawCloudPuffs(elapsed: elapsed)
        drawSparkle(center: NSPoint(x: 320, y: 157), size: 14, elapsed: elapsed, delay: 0)
        drawSparkle(center: NSPoint(x: 90, y: 174), size: 8, elapsed: elapsed, delay: 0.5)

        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawCloudPuffs(elapsed: CGFloat) {
        let puffs: [(x: CGFloat, y: CGFloat, size: CGFloat, delay: CGFloat)] = [
            (96, 104, 22, 0.0),
            (302, 116, 18, 0.7),
            (82, 264, 14, 1.4),
            (315, 284, 16, 2.1)
        ]
        for puff in puffs {
            let cycle = ((elapsed + puff.delay).truncatingRemainder(dividingBy: 3.2)) / 3.2
            let rise = 28 * cycle
            let drift = 8 * sin((elapsed + puff.delay) * 1.7)
            let alpha = max(0, sin(cycle * .pi)) * 0.32
            let rect = NSRect(
                x: puff.x + drift - puff.size / 2,
                y: puff.y - rise - puff.size / 2,
                width: puff.size,
                height: puff.size * 0.68
            )
            NSColor.white.withAlphaComponent(alpha).setFill()
            NSBezierPath(ovalIn: rect).fill()
            NSBezierPath(ovalIn: rect.offsetBy(dx: puff.size * 0.28, dy: -puff.size * 0.08)).fill()
            NSBezierPath(ovalIn: rect.offsetBy(dx: -puff.size * 0.24, dy: -puff.size * 0.04)).fill()
        }
    }

    private func drawBlobBody() {
        let path = NSBezierPath()
        path.move(to: NSPoint(x: 200, y: 100))
        path.curve(to: NSPoint(x: 275, y: 125), controlPoint1: NSPoint(x: 230, y: 100), controlPoint2: NSPoint(x: 255, y: 105))
        path.curve(to: NSPoint(x: 300, y: 200), controlPoint1: NSPoint(x: 295, y: 145), controlPoint2: NSPoint(x: 300, y: 170))
        path.curve(to: NSPoint(x: 275, y: 275), controlPoint1: NSPoint(x: 300, y: 230), controlPoint2: NSPoint(x: 295, y: 255))
        path.curve(to: NSPoint(x: 200, y: 300), controlPoint1: NSPoint(x: 255, y: 295), controlPoint2: NSPoint(x: 230, y: 300))
        path.curve(to: NSPoint(x: 125, y: 275), controlPoint1: NSPoint(x: 170, y: 300), controlPoint2: NSPoint(x: 145, y: 295))
        path.curve(to: NSPoint(x: 100, y: 200), controlPoint1: NSPoint(x: 105, y: 255), controlPoint2: NSPoint(x: 100, y: 230))
        path.curve(to: NSPoint(x: 125, y: 125), controlPoint1: NSPoint(x: 100, y: 170), controlPoint2: NSPoint(x: 105, y: 145))
        path.curve(to: NSPoint(x: 200, y: 100), controlPoint1: NSPoint(x: 145, y: 105), controlPoint2: NSPoint(x: 170, y: 100))
        path.close()
        NSColor(red: 0.44, green: 0.86, blue: 0.95, alpha: 1).setFill()
        path.fill()
    }

    private func drawHat(elapsed: CGFloat) {
        let angle = 2 * sin((elapsed / 1.5) * 2 * .pi)

        NSGraphicsContext.saveGraphicsState()
        let transform = NSAffineTransform()
        transform.translateX(by: 200, yBy: 90)
        transform.rotate(byDegrees: angle)
        transform.translateX(by: -200, yBy: -90)
        transform.concat()

        NSColor(red: 0.17, green: 0.24, blue: 0.31, alpha: 1).setFill()
        NSBezierPath(ovalIn: NSRect(x: 120, y: 100, width: 160, height: 30)).fill()

        let top = NSBezierPath()
        top.move(to: NSPoint(x: 140, y: 115))
        top.curve(to: NSPoint(x: 200, y: 65), controlPoint1: NSPoint(x: 140, y: 88), controlPoint2: NSPoint(x: 160, y: 68))
        top.curve(to: NSPoint(x: 260, y: 115), controlPoint1: NSPoint(x: 240, y: 68), controlPoint2: NSPoint(x: 260, y: 88))
        top.close()
        NSColor(red: 0.20, green: 0.29, blue: 0.37, alpha: 1).setFill()
        top.fill()

        NSColor(red: 0.91, green: 0.30, blue: 0.24, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 135, y: 110, width: 130, height: 8), xRadius: 2, yRadius: 2).fill()

        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawCheeksAndFace(elapsed: CGFloat) {
        NSColor(red: 1, green: 0.71, blue: 0.76, alpha: 0.6).setFill()
        NSBezierPath(ovalIn: NSRect(x: 140, y: 190, width: 30, height: 30)).fill()
        NSBezierPath(ovalIn: NSRect(x: 230, y: 190, width: 30, height: 30)).fill()

        NSColor(red: 0.10, green: 0.10, blue: 0.10, alpha: 1).setFill()
        NSBezierPath(ovalIn: NSRect(x: 163, y: 168, width: 24, height: 24)).fill()
        NSBezierPath(ovalIn: NSRect(x: 213, y: 168, width: 24, height: 24)).fill()

        NSColor.white.setFill()
        NSBezierPath(ovalIn: NSRect(x: 173, y: 172, width: 10, height: 10)).fill()
        NSBezierPath(ovalIn: NSRect(x: 178, y: 180, width: 4, height: 4)).fill()
        NSBezierPath(ovalIn: NSRect(x: 223, y: 172, width: 10, height: 10)).fill()
        NSBezierPath(ovalIn: NSRect(x: 228, y: 180, width: 4, height: 4)).fill()

        let smileDepth = 236.5 - 1.5 * cos((elapsed / 2) * 2 * .pi)
        let smile = NSBezierPath()
        smile.move(to: NSPoint(x: 175, y: 220))
        smile.curve(to: NSPoint(x: 225, y: 220), controlPoint1: NSPoint(x: 188, y: smileDepth), controlPoint2: NSPoint(x: 212, y: smileDepth))
        smile.lineWidth = 3
        smile.lineCapStyle = .round
        NSColor(red: 0.10, green: 0.10, blue: 0.10, alpha: 1).setStroke()
        smile.stroke()
    }

    private func drawMagnifyingGlass(elapsed: CGFloat) {
        let theta = (elapsed / 8) * 2 * .pi
        let value = (
            x: -80 + 48 * sin(theta) - 28 * sin(2 * theta),
            y: -50 - 12 * cos(theta),
            rotation: 28 * sin(theta - (.pi / 8))
        )

        NSGraphicsContext.saveGraphicsState()
        let transform = NSAffineTransform()
        transform.translateX(by: value.x, yBy: value.y)
        transform.translateX(by: 280, yBy: 240)
        transform.rotate(byDegrees: value.rotation)
        transform.translateX(by: -280, yBy: -240)
        transform.concat()

        NSColor(red: 0.89, green: 0.95, blue: 0.99, alpha: 0.4).setFill()
        NSBezierPath(ovalIn: NSRect(x: 250, y: 210, width: 60, height: 60)).fill()

        let rim = NSBezierPath(ovalIn: NSRect(x: 245, y: 205, width: 70, height: 70))
        rim.lineWidth = 6
        NSColor(red: 0.36, green: 0.25, blue: 0.22, alpha: 1).setStroke()
        rim.stroke()

        NSColor(red: 1, green: 1, blue: 1, alpha: 0.7).setFill()
        NSBezierPath(ovalIn: NSRect(x: 262, y: 222, width: 16, height: 16)).fill()
        NSColor(red: 1, green: 1, blue: 1, alpha: 0.5).setFill()
        NSBezierPath(ovalIn: NSRect(x: 281, y: 241, width: 8, height: 8)).fill()

        NSColor(red: 0.55, green: 0.27, blue: 0.07, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 276, y: 275, width: 8, height: 50), xRadius: 4, yRadius: 4).fill()

        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawSparkle(center: NSPoint, size: CGFloat, elapsed: CGFloat, delay: CGFloat) {
        let pulse = 0.5 + 0.5 * sin(((elapsed + delay) / 1.5) * 2 * .pi)
        let scale = 0.8 + 0.4 * pulse
        let alpha = 0.3 + 0.7 * pulse
        let half = size / 2 * scale
        let path = NSBezierPath()
        path.move(to: NSPoint(x: center.x, y: center.y - half))
        path.line(to: NSPoint(x: center.x + half * 0.25, y: center.y - half * 0.25))
        path.line(to: NSPoint(x: center.x + half, y: center.y))
        path.line(to: NSPoint(x: center.x + half * 0.25, y: center.y + half * 0.25))
        path.line(to: NSPoint(x: center.x, y: center.y + half))
        path.line(to: NSPoint(x: center.x - half * 0.25, y: center.y + half * 0.25))
        path.line(to: NSPoint(x: center.x - half, y: center.y))
        path.line(to: NSPoint(x: center.x - half * 0.25, y: center.y - half * 0.25))
        path.close()
        NSColor(red: 1, green: 0.84, blue: 0, alpha: alpha).setFill()
        path.fill()
    }

}

final class LoadingWindow: NSWindow {
    private let detectiveBlob = DetectiveBlobView()
    private let label = NSTextField(labelWithString: "Thinking...")
    private let stopButton = PillButton(
        title: "Stop",
        fillColor: NSColor.systemRed,
        activeFillColor: NSColor.systemRed
    )
    private var startedAt: Date?
    private var timer: Timer?
    private var dotStep = 0
    var onStop: (() -> Void)?

    init() {
        let frame = NSScreen.main?.frame ?? .zero
        super.init(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: false)
        level = .screenSaver
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        backgroundColor = NSColor.black.withAlphaComponent(0.38)
        isOpaque = false

        let content = NSView(frame: frame)
        content.wantsLayer = true
        content.layer?.backgroundColor = NSColor.clear.cgColor
        contentView = content

        detectiveBlob.frame = NSRect(x: frame.midX - 135, y: frame.midY - 130, width: 270, height: 270)
        content.addSubview(detectiveBlob)

        label.textColor = .white
        label.font = .systemFont(ofSize: 21, weight: .semibold)
        label.alignment = .center
        label.frame = NSRect(x: frame.midX - 180, y: frame.midY - 178, width: 360, height: 30)
        content.addSubview(label)

        stopButton.target = self
        stopButton.action = #selector(stopThinking)
        stopButton.frame = NSRect(x: frame.midX - 62, y: frame.midY - 232, width: 124, height: 42)
        content.addSubview(stopButton)
    }

    func show() {
        startedAt = Date()
        dotStep = 0
        updateThinkingLabel()
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 0.55, repeats: true) { [weak self] _ in
            self?.updateThinkingLabel()
        }
        detectiveBlob.startAnimation()
        orderFrontRegardless()
    }

    func hide() {
        timer?.invalidate()
        timer = nil
        startedAt = nil
        dotStep = 0
        detectiveBlob.stopAnimation()
        orderOut(nil)
    }

    private func updateThinkingLabel() {
        dotStep = (dotStep + 1) % 4
        label.stringValue = "Thinking" + String(repeating: ".", count: dotStep)
    }

    @objc private func stopThinking() {
        onStop?()
    }
}

final class ScanningBoxesWindow: NSWindow {
    private let scanningView: ScanningBoxesView

    init() {
        let frame = NSScreen.main?.frame ?? .zero
        scanningView = ScanningBoxesView(frame: frame)
        super.init(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: false)
        level = NSWindow.Level(Int(CGWindowLevelForKey(.screenSaverWindow)) + 1)
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        backgroundColor = .clear
        isOpaque = false
        ignoresMouseEvents = true
        contentView = scanningView
    }

    func start(detections: [DetectionItem], screenshotSize: NSSize) {
        scanningView.start(detections: detections, screenshotSize: screenshotSize)
        orderFrontRegardless()
    }

    func stop() {
        scanningView.stop()
        orderOut(nil)
    }
}

final class ScanningBoxesView: NSView {
    private let colors: [NSColor] = [
        NSColor(red: 0.45, green: 0.62, blue: 0.49, alpha: 0.58),
        NSColor(red: 0.47, green: 0.56, blue: 0.68, alpha: 0.58),
        NSColor(red: 0.67, green: 0.48, blue: 0.46, alpha: 0.58),
        NSColor(red: 0.66, green: 0.58, blue: 0.43, alpha: 0.58),
        NSColor(red: 0.57, green: 0.50, blue: 0.66, alpha: 0.58),
    ]
    private let bubbleMessages = [
        "Case file open.",
        "Dusting buttons for clues.",
        "The trail is warming up.",
        "Interrogating the icons.",
        "Checking the usual suspects.",
        "This clue looks suspicious.",
        "Following the control trail.",
        "Magnifier says: almost.",
        "The case is narrowing.",
        "One more clue to verify."
    ]
    private var detections: [DetectionItem] = []
    private var screenshotSize: NSSize = .zero
    private var activeBoxes: [(detection: DetectionItem, revealedAt: TimeInterval, life: TimeInterval)] = []
    private var activeBubble: (message: String, shownAt: TimeInterval)?
    private var shownBubbleCount = 0
    private var nextDetectionIndex = 0
    private var timer: Timer?
    private var startedAt = Date()
    private var nextRevealAt: TimeInterval = 0.5

    override var isFlipped: Bool { true }

    func start(detections: [DetectionItem], screenshotSize: NSSize) {
        self.detections = detections
            .filter { $0.box.count == 4 && ($0.confidence ?? 0) > 0.6 }
            .sorted { lhs, rhs in
                let lhsY = lhs.box[1]
                let rhsY = rhs.box[1]
                if abs(lhsY - rhsY) > 28 {
                    return lhsY < rhsY
                }
                return lhs.box[0] < rhs.box[0]
            }
        self.screenshotSize = screenshotSize
        activeBoxes = []
        activeBubble = nil
        shownBubbleCount = 0
        nextDetectionIndex = 0
        startedAt = Date()
        nextRevealAt = 0.5
        needsDisplay = true
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            if self.detections.isEmpty {
                return
            }
            let elapsed = Date().timeIntervalSince(self.startedAt)
            self.activeBoxes.removeAll { elapsed - $0.revealedAt > $0.life }
            if self.activeBoxes.count > 42 {
                self.activeBoxes.removeFirst(self.activeBoxes.count - 42)
            }
            if let bubble = self.activeBubble, elapsed - bubble.shownAt > 4.6 {
                self.activeBubble = nil
            }

            while elapsed >= self.nextRevealAt {
                if let visible = self.nextVisibleDetection() {
                    let detection = visible.detection
                    let life = 13.0 + Double((self.nextDetectionIndex % 5)) * 1.7
                    self.activeBoxes.append((detection: detection, revealedAt: elapsed, life: life))
                    if self.activeBubble == nil && self.shownBubbleCount < self.bubbleMessages.count && self.nextDetectionIndex % 8 == 1 {
                        self.activeBubble = (message: self.bubbleMessages[self.shownBubbleCount], shownAt: elapsed)
                        self.shownBubbleCount += 1
                    }
                    self.nextDetectionIndex = visible.nextIndex
                } else {
                    self.nextDetectionIndex += 1
                }
                self.nextRevealAt += self.revealInterval(nextRevealAt: self.nextRevealAt)
            }

            self.needsDisplay = true
        }
    }

    private func nextVisibleDetection() -> (detection: DetectionItem, nextIndex: Int)? {
        guard !detections.isEmpty else { return nil }
        let protectedRect = logoProtectionRect()
        let scaleX = bounds.width / max(screenshotSize.width, 1)
        let scaleY = bounds.height / max(screenshotSize.height, 1)
        for offset in 0..<detections.count {
            let detectionIndex = (nextDetectionIndex + offset) % detections.count
            let detection = detections[detectionIndex]
            let box = detection.box
            let rect = NSRect(
                x: box[0] * scaleX,
                y: box[1] * scaleY,
                width: (box[2] - box[0]) * scaleX,
                height: (box[3] - box[1]) * scaleY
            )
            if !rect.intersects(protectedRect) {
                return (detection: detection, nextIndex: detectionIndex + 1)
            }
        }
        return nil
    }

    private func revealInterval(nextRevealAt: TimeInterval) -> TimeInterval {
        let startRate = 1.0 / 0.5
        let rampedRate = startRate * pow(1.33, nextRevealAt)
        let cappedRate = min(8.0, rampedRate)
        return 1.0 / cappedRate
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        detections = []
        activeBoxes = []
        activeBubble = nil
        shownBubbleCount = 0
        nextDetectionIndex = 0
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        guard screenshotSize.width > 0, screenshotSize.height > 0 else { return }
        let scaleX = bounds.width / screenshotSize.width
        let scaleY = bounds.height / screenshotSize.height
        for (index, activeBox) in activeBoxes.enumerated() {
            let detection = activeBox.detection
            let box = detection.box
            let rect = NSRect(
                x: box[0] * scaleX,
                y: box[1] * scaleY,
                width: (box[2] - box[0]) * scaleX,
                height: (box[3] - box[1]) * scaleY
            )
            let color = colors[index % colors.count]
            let age = Date().timeIntervalSince(startedAt) - activeBox.revealedAt
            let progress = max(0, min(1, age / activeBox.life))
            drawBox(rect: rect, label: detection.element_id, color: color, progress: progress)
        }
        drawBubbleIfNeeded()
    }

    private func drawBox(rect: NSRect, label: String, color: NSColor, progress: Double) {
        let fadeIn = min(1, progress / 0.18)
        let fadeOut = progress > 0.82 ? max(0, 1 - ((progress - 0.82) / 0.18)) : 1
        let alpha = CGFloat(fadeIn * fadeOut)
        let pulse = 0.5 + 0.5 * sin(CGFloat(progress) * .pi * 6)
        let drawColor = color.withAlphaComponent(color.alphaComponent * alpha)
        let lineWidth: CGFloat = 0.95 + 0.35 * pulse
        let border = NSBezierPath(rect: rect)
        border.lineWidth = lineWidth
        drawColor.setStroke()
        border.stroke()

        let sweepX = rect.minX + rect.width * CGFloat(progress)
        let sweep = NSBezierPath()
        sweep.move(to: NSPoint(x: sweepX, y: rect.minY))
        sweep.line(to: NSPoint(x: sweepX, y: rect.maxY))
        sweep.lineWidth = 1
        color.withAlphaComponent(0.25 * alpha).setStroke()
        sweep.stroke()

        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 15, weight: .semibold),
            .foregroundColor: NSColor.white.withAlphaComponent(alpha)
        ]
        let text = NSString(string: label)
        let size = text.size(withAttributes: attributes)
        let labelRect = NSRect(
            x: rect.minX,
            y: max(0, rect.minY - size.height - 5),
            width: size.width + 10,
            height: size.height + 5
        )
        drawColor.setFill()
        NSBezierPath(roundedRect: labelRect, xRadius: 4, yRadius: 4).fill()
        text.draw(in: labelRect.insetBy(dx: 5, dy: 2.5), withAttributes: attributes)
    }

    private func drawBubbleIfNeeded() {
        guard let activeBubble else { return }
        let age = Date().timeIntervalSince(startedAt) - activeBubble.shownAt
        let alpha = CGFloat(min(1, age / 0.25) * min(1, max(0, 4.6 - age) / 1.2))
        guard alpha > 0 else { return }

        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 24, weight: .bold),
            .foregroundColor: NSColor.white.withAlphaComponent(alpha)
        ]
        let text = NSString(string: activeBubble.message)
        let size = text.size(withAttributes: attributes)
        let padding: CGFloat = 18
        let bubbleSize = NSSize(width: size.width + padding * 2, height: size.height + padding * 2)
        let bubbleRect = movingBubbleRect(size: bubbleSize, age: age)
        NSColor(red: 0.00, green: 0.46, blue: 1.00, alpha: 0.98 * alpha).setFill()
        NSBezierPath(roundedRect: bubbleRect, xRadius: 22, yRadius: 22).fill()

        NSColor.white.withAlphaComponent(0.82 * alpha).setStroke()
        let outline = NSBezierPath(roundedRect: bubbleRect, xRadius: 22, yRadius: 22)
        outline.lineWidth = 2
        outline.stroke()

        text.draw(in: bubbleRect.insetBy(dx: padding, dy: padding), withAttributes: attributes)
    }

    private func movingBubbleRect(size: NSSize, age: TimeInterval) -> NSRect {
        let margin: CGFloat = 30
        let safeMaxX = max(margin, bounds.maxX - size.width - margin)
        let safeMaxY = max(margin, bounds.maxY - size.height - margin)
        let protected = logoProtectionRect().insetBy(dx: -36, dy: -24)
        let rightX = protected.maxX + 34
        let leftX = protected.minX - size.width - 34
        let topY = protected.minY + 88
        let bottomY = protected.maxY - size.height - 88
        let anchors = [
            NSPoint(x: rightX, y: topY),
            NSPoint(x: leftX, y: topY),
            NSPoint(x: rightX, y: bottomY),
            NSPoint(x: leftX, y: bottomY)
        ]
        let anchor = anchors[max(0, shownBubbleCount - 1) % anchors.count]
        let baseX = min(max(margin, anchor.x), safeMaxX)
        let baseY = min(max(margin, anchor.y), safeMaxY)

        let driftX = CGFloat(sin(age * 1.15)) * 18 + CGFloat(sin(age * 0.41)) * 7
        let driftY = CGFloat(cos(age * 0.92)) * 12 + CGFloat(sin(age * 0.53)) * 5
        return NSRect(
            x: min(max(margin, baseX + driftX), safeMaxX),
            y: min(max(margin, baseY + driftY), safeMaxY),
            width: size.width,
            height: size.height
        )
    }

    private func logoProtectionRect() -> NSRect {
        NSRect(
            x: bounds.midX - 230,
            y: bounds.midY - 265,
            width: 460,
            height: 560
        )
    }
}

final class HighlightWindow: NSWindow {
    private let overlayView: HighlightView
    private var globalClickMonitor: Any?
    private var localClickMonitor: Any?
    private var ignoredClickWindowNumbers: Set<Int> = []
    private var didDismiss = false
    var onDismiss: (() -> Void)?

    init(imageSize: NSSize, box: PixelBox, message: String) {
        let frame = NSScreen.main?.frame ?? .zero
        overlayView = HighlightView(frame: frame, screenshotSize: imageSize, box: box, message: message)
        super.init(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: false)
        level = .screenSaver
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        backgroundColor = .clear
        isOpaque = false
        ignoresMouseEvents = true
        contentView = overlayView
    }

    func showForTwentySeconds(ignoringClickWindowNumbers windowNumbers: Set<Int> = []) {
        ignoredClickWindowNumbers = windowNumbers
        orderFrontRegardless()
        overlayView.startAnimation()
        startClickMonitor()
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in
            self?.dismiss()
        }
    }

    private func startClickMonitor() {
        let mask: NSEvent.EventTypeMask = [.leftMouseDown, .rightMouseDown, .otherMouseDown]
        globalClickMonitor = NSEvent.addGlobalMonitorForEvents(matching: mask) { [weak self] _ in
            DispatchQueue.main.async {
                self?.dismiss()
            }
        }
        localClickMonitor = NSEvent.addLocalMonitorForEvents(matching: mask) { [weak self] event in
            if self?.ignoredClickWindowNumbers.contains(event.windowNumber) != true {
                self?.dismiss()
            }
            return event
        }
    }

    private func dismiss() {
        guard !didDismiss else { return }
        didDismiss = true
        if let globalClickMonitor {
            NSEvent.removeMonitor(globalClickMonitor)
            self.globalClickMonitor = nil
        }
        if let localClickMonitor {
            NSEvent.removeMonitor(localClickMonitor)
            self.localClickMonitor = nil
        }
        orderOut(nil)
        onDismiss?()
    }
}

struct HighlightLayout {
    static func targetRect(bounds: NSRect, screenshotSize: NSSize, box: PixelBox) -> NSRect {
        let scaleX = bounds.width / screenshotSize.width
        let scaleY = bounds.height / screenshotSize.height
        return NSRect(
            x: box.x1 * scaleX,
            y: box.y1 * scaleY,
            width: (box.x2 - box.x1) * scaleX,
            height: (box.y2 - box.y1) * scaleY
        )
    }

    static func messageBubbleRect(bounds: NSRect, targetRect rect: NSRect, message: String) -> NSRect {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 22, weight: .semibold)
        ]
        let size = NSString(string: message).size(withAttributes: attributes)
        let padding: CGFloat = 16
        let bubbleWidth = min(max(size.width + padding * 2, 260), bounds.width - 40)
        let bubbleHeight = size.height + padding * 2
        var x = rect.midX - bubbleWidth / 2
        var y = rect.minY - bubbleHeight - 18
        if y < 20 {
            y = rect.maxY + 18
        }
        x = max(20, min(x, bounds.width - bubbleWidth - 20))
        return NSRect(x: x, y: y, width: bubbleWidth, height: bubbleHeight)
    }

    static func replayWindowFrame(screenFrame: NSRect, screenshotSize: NSSize, box: PixelBox, message: String) -> NSRect {
        let overlayBounds = NSRect(origin: .zero, size: screenFrame.size)
        let target = targetRect(bounds: overlayBounds, screenshotSize: screenshotSize, box: box)
        let bubble = messageBubbleRect(bounds: overlayBounds, targetRect: target, message: message)
        let size = NSSize(width: 118, height: 38)

        var overlayX = bubble.maxX - size.width
        var overlayY = bubble.maxY + 8
        if overlayY + size.height > overlayBounds.maxY - 16 {
            overlayY = bubble.minY - size.height - 8
        }

        overlayX = max(20, min(overlayX, overlayBounds.maxX - size.width - 20))
        overlayY = max(20, min(overlayY, overlayBounds.maxY - size.height - 20))

        let x = screenFrame.minX + overlayX
        let y = screenFrame.maxY - overlayY - size.height
        return NSRect(origin: NSPoint(x: x, y: y), size: size)
    }
}

final class ReplayWindow: NSPanel {
    private let replayButton = PillButton(
        title: "Replay",
        fillColor: NSColor.systemBlue,
        activeFillColor: NSColor.systemBlue
    )
    var onReplay: (() -> Void)?

    init(frame: NSRect) {
        super.init(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: false)
        isFloatingPanel = true
        level = .screenSaver
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        backgroundColor = .clear
        isOpaque = false
        hasShadow = true

        let content = NSView(frame: NSRect(origin: .zero, size: frame.size))
        content.wantsLayer = true
        content.layer?.backgroundColor = NSColor.black.withAlphaComponent(0.2).cgColor
        content.layer?.cornerRadius = 18
        contentView = content

        replayButton.target = self
        replayButton.action = #selector(replay)
        replayButton.frame = NSRect(x: 6, y: 4, width: frame.width - 12, height: frame.height - 8)
        content.addSubview(replayButton)
    }

    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    func showForTwentySeconds() {
        orderFrontRegardless()
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in
            self?.orderOut(nil)
        }
    }

    @objc private func replay() {
        onReplay?()
    }
}

final class HighlightView: NSView {
    private let screenshotSize: NSSize
    private let box: PixelBox
    private let message: String
    private var pulse: CGFloat = 0
    private var timer: Timer?

    init(frame: NSRect, screenshotSize: NSSize, box: PixelBox, message: String) {
        self.screenshotSize = screenshotSize
        self.box = box
        self.message = message
        super.init(frame: frame)
        wantsLayer = true
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var isFlipped: Bool { true }

    func startAnimation() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.pulse += 0.08
            self.needsDisplay = true
        }
    }

    override func draw(_ dirtyRect: NSRect) {
        guard screenshotSize.width > 0, screenshotSize.height > 0 else { return }

        let rect = HighlightLayout.targetRect(bounds: bounds, screenshotSize: screenshotSize, box: box)

        NSColor.black.withAlphaComponent(0.18).setFill()
        bounds.fill()

        let glow = 6 + (sin(pulse) + 1) * 5
        let path = NSBezierPath(roundedRect: rect.insetBy(dx: -glow, dy: -glow), xRadius: 10, yRadius: 10)
        NSColor.systemYellow.withAlphaComponent(0.26).setFill()
        path.fill()

        let border = NSBezierPath(roundedRect: rect.insetBy(dx: -5, dy: -5), xRadius: 8, yRadius: 8)
        border.lineWidth = 5
        NSColor.systemYellow.setStroke()
        border.stroke()

        drawMessage(near: rect)
    }

    private func drawMessage(near rect: NSRect) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 22, weight: .semibold),
            .foregroundColor: NSColor.white
        ]
        let text = NSString(string: message)
        let padding: CGFloat = 16
        let bubbleRect = HighlightLayout.messageBubbleRect(bounds: bounds, targetRect: rect, message: message)
        let bubble = NSBezierPath(roundedRect: bubbleRect, xRadius: 16, yRadius: 16)
        NSColor.black.withAlphaComponent(0.82).setFill()
        bubble.fill()

        text.draw(
            in: bubbleRect.insetBy(dx: padding, dy: padding),
            withAttributes: attributes
        )
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let paths = Paths.detect()
    private lazy var elevenLabs = ElevenLabsClient(paths: paths)
    private var hotKey: HotKeyManager?
    private var commandBar: CommandBarWindow?
    private var loadingWindow: LoadingWindow?
    private var scanningWindow: ScanningBoxesWindow?
    private var scanPollTimer: Timer?
    private var highlightWindow: HighlightWindow?
    private var replayWindow: ReplayWindow?
    private var activeProcess: Process?
    private var currentRunStartedAt: Date?
    private var didCancelCurrentRun = false
    private var lastSpokenMessage = ""

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        AppLogger.shared.configure(paths.appLogURL)
        commandBar = CommandBarWindow(paths: paths, elevenLabs: elevenLabs)
        loadingWindow = LoadingWindow()
        scanningWindow = ScanningBoxesWindow()
        loadingWindow?.onStop = { [weak self] in
            self?.cancelCurrentRun()
        }
        commandBar?.onSubmit = { [weak self] intent in
            self?.runPipeline(intent: intent)
        }
        hotKey = HotKeyManager { [weak self] in
            self?.commandBar?.show()
        }
        print("ScreenIntentApp is running. Press Command+Shift+Space.")
    }

    private func runPipeline(intent: String) {
        guard activeProcess == nil else { return }
        do {
            didCancelCurrentRun = false
            currentRunStartedAt = Date()
            try FileManager.default.createDirectory(at: paths.runtimeDir, withIntermediateDirectories: true)
            try captureScreenshot()
            try writeRunEnv(intent: intent)
            loadingWindow?.show()
            startScanningWhenDetectionsAreReady()
            runCompletePipeline()
        } catch {
            currentRunStartedAt = nil
            loadingWindow?.hide()
            stopScanning()
            showError(error.localizedDescription)
        }
    }

    private func captureScreenshot() throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        process.arguments = ["-x", paths.screenshotURL.path]
        try process.run()
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            throw NSError(domain: "ScreenIntentApp", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Screenshot failed. Grant Screen Recording permission if macOS asks."
            ])
        }
    }

    private func writeRunEnv(intent: String) throws {
        let rootEnvURL = paths.repoDir.appendingPathComponent(".env")
        var envText = (try? String(contentsOf: rootEnvURL)) ?? ""
        if !envText.hasSuffix("\n") {
            envText += "\n"
        }
        envText += "TEST_IMAGE='\(escapeEnv(paths.screenshotURL.path))'\n"
        envText += "USER_INTENT='\(escapeEnv(intent))'\n"
        try envText.write(to: paths.runEnvURL, atomically: true, encoding: .utf8)
    }

    private func escapeEnv(_ value: String) -> String {
        value.replacingOccurrences(of: "'", with: "'\"'\"'")
    }

    private func runCompletePipeline() {
        let process = Process()
        process.executableURL = paths.pythonURL
        process.arguments = [paths.completeRunURL.path]
        process.currentDirectoryURL = paths.repoDir
        var environment = ProcessInfo.processInfo.environment
        environment["PIPELINE_ENV_FILE"] = paths.runEnvURL.path
        process.environment = environment

        FileManager.default.createFile(atPath: paths.runLogURL.path, contents: nil)
        if let logHandle = try? FileHandle(forWritingTo: paths.runLogURL) {
            process.standardOutput = logHandle
            process.standardError = logHandle
        }

        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                self?.activeProcess = nil
                self?.loadingWindow?.hide()
                self?.stopScanning()
                if self?.didCancelCurrentRun == true {
                    AppLogger.shared.log("Pipeline cancellation completed")
                    self?.didCancelCurrentRun = false
                    self?.currentRunStartedAt = nil
                    return
                }
                if process.terminationStatus == 0 || self?.freshOutputFilesReady() == true {
                    self?.showResult()
                } else {
                    self?.showError(self?.pipelineFailureMessage(status: process.terminationStatus) ?? "Pipeline failed.")
                }
            }
        }

        do {
            activeProcess = process
            try process.run()
        } catch {
            activeProcess = nil
            loadingWindow?.hide()
            stopScanning()
            showError(error.localizedDescription)
        }
    }

    private func startScanningWhenDetectionsAreReady() {
        stopScanning()
        scanPollTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] timer in
            guard let self else { return }
            guard let startedAt = self.currentRunStartedAt else {
                timer.invalidate()
                self.scanPollTimer = nil
                return
            }
            guard
                FileManager.default.fileExists(atPath: self.paths.detectionsURL.path),
                FileManager.default.fileExists(atPath: self.paths.inputImageURL.path),
                self.fileWasUpdated(self.paths.detectionsURL, after: startedAt),
                self.fileWasUpdated(self.paths.inputImageURL, after: startedAt)
            else {
                return
            }
            do {
                let detectionsData = try Data(contentsOf: self.paths.detectionsURL)
                let detections = try JSONDecoder().decode([DetectionItem].self, from: detectionsData)
                let imageSize = try self.screenshotPixelSize()
                self.scanningWindow?.start(detections: detections, screenshotSize: imageSize)
                timer.invalidate()
                self.scanPollTimer = nil
                AppLogger.shared.log("Started progressive scanning boxes from fresh detections.json: \(detections.count)")
            } catch {
                AppLogger.shared.log("Waiting for valid detections before scanning: \(error.localizedDescription)")
            }
        }
    }

    private func fileWasUpdated(_ url: URL, after startedAt: Date) -> Bool {
        guard
            let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
            let modifiedAt = attributes[.modificationDate] as? Date
        else {
            return false
        }
        return modifiedAt >= startedAt.addingTimeInterval(-1)
    }

    private func stopScanning() {
        scanPollTimer?.invalidate()
        scanPollTimer = nil
        scanningWindow?.stop()
    }

    private func cancelCurrentRun() {
        guard let activeProcess else {
            loadingWindow?.hide()
            return
        }
        AppLogger.shared.log("User requested pipeline cancellation")
        didCancelCurrentRun = true
        currentRunStartedAt = nil
        activeProcess.terminate()
        loadingWindow?.hide()
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self, weak activeProcess] in
            guard let process = activeProcess, process.isRunning else { return }
            AppLogger.shared.log("Pipeline still running after terminate; interrupting")
            process.interrupt()
            self?.activeProcess = nil
        }
    }

    private func showResult() {
        do {
            let resolutionData = try Data(contentsOf: paths.conflictResolutionURL)
            let resolution = try JSONDecoder().decode(ConflictResolution.self, from: resolutionData)
            guard resolution.selected_element_id != "NONE" else {
                let message = resolution.direction_for_user.isEmpty ? resolution.plaintext_response : resolution.direction_for_user
                speak(message)
                showError(message)
                return
            }

            let actionsData = try Data(contentsOf: paths.finalActionButtonsURL)
            let actions = try JSONDecoder().decode([String: ActionButton].self, from: actionsData)
            guard let action = actions[resolution.selected_element_id] else {
                showError("I found \(resolution.selected_element_id), but could not find its bounding box.")
                return
            }

            let imageSize = try screenshotPixelSize()
            let highlight = HighlightWindow(
                imageSize: imageSize,
                box: action.box,
                message: resolution.direction_for_user
            )
            let screenFrame = NSScreen.main?.frame ?? .zero
            let replayFrame = HighlightLayout.replayWindowFrame(
                screenFrame: screenFrame,
                screenshotSize: imageSize,
                box: action.box,
                message: resolution.direction_for_user
            )
            let replay = ReplayWindow(frame: replayFrame)
            replay.onReplay = { [weak self] in
                guard let self else { return }
                self.speak(self.lastSpokenMessage)
            }
            highlight.onDismiss = { [weak self] in
                self?.elevenLabs.stopSpeaking()
                self?.highlightWindow = nil
                self?.replayWindow?.orderOut(nil)
                self?.replayWindow = nil
            }
            highlightWindow = highlight
            replayWindow = replay
            replay.showForTwentySeconds()
            highlight.showForTwentySeconds(ignoringClickWindowNumbers: [replay.windowNumber])
            speak(resolution.direction_for_user)
            currentRunStartedAt = nil
        } catch {
            currentRunStartedAt = nil
            showError(error.localizedDescription)
        }
    }

    private func speak(_ message: String) {
        let text = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        lastSpokenMessage = text
        elevenLabs.stopSpeaking()
        elevenLabs.speak(text) { result in
            if case .failure(let error) = result {
                print("ElevenLabs TTS failed: \(error.localizedDescription)")
            }
        }
    }

    private func freshOutputFilesReady() -> Bool {
        guard let startedAt = currentRunStartedAt else { return false }
        return [paths.conflictResolutionURL, paths.finalActionButtonsURL].allSatisfy { url in
            guard
                FileManager.default.fileExists(atPath: url.path),
                let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
                let modifiedAt = attributes[.modificationDate] as? Date
            else {
                return false
            }
            return modifiedAt >= startedAt.addingTimeInterval(-2)
        }
    }

    private func pipelineFailureMessage(status: Int32) -> String {
        let tail = recentLogTail()
        guard !tail.isEmpty else {
            return "Pipeline failed with exit code \(status). No runtime log was written."
        }
        return "Pipeline failed with exit code \(status).\n\nLast log lines:\n\(tail)"
    }

    private func recentLogTail() -> String {
        guard let text = try? String(contentsOf: paths.runLogURL, encoding: .utf8) else {
            return ""
        }
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        return lines.suffix(22).joined(separator: "\n")
    }

    private func screenshotPixelSize() throws -> NSSize {
        let data = try Data(contentsOf: paths.inputImageURL)
        guard
            let image = NSImage(data: data),
            let rep = image.representations.first
        else {
            throw NSError(domain: "ScreenIntentApp", code: 2, userInfo: [
                NSLocalizedDescriptionKey: "Could not read screenshot size."
            ])
        }
        return NSSize(width: rep.pixelsWide, height: rep.pixelsHigh)
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Screen intent failed"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
