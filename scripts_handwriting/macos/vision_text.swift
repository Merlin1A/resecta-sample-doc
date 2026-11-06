// Runs Apple's Vision text recognition (VNRecognizeTextRequest, accurate level, language correction
// on) on each image and prints one JSON document: the macOS version, the request revision, the
// languages asked for, and per image every observation's top string, confidence and box, with the
// box of each space-separated word and of each character.
//
// Usage:  vision_text --languages zh-Hans,en-US page1.png page2.png > out.json
//         vision_text --list-languages                 # the languages this macOS supports
// Boxes are Vision's normalized image coordinates (0-1, bottom-left origin), to 6 decimals.
//
// Build:  swiftc -O -o vision_text vision_text.swift

import Foundation
import ImageIO
import Vision

func box(_ r: CGRect) -> [Double] {
    [r.minX, r.minY, r.maxX, r.maxY].map { (Double($0) * 1_000_000).rounded() / 1_000_000 }
}

func fail(_ m: String) -> Never {
    FileHandle.standardError.write("vision_text: \(m)\n".data(using: .utf8)!)
    exit(1)
}

func emit(_ obj: Any) {
    let data = try! JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

func request(_ languages: [String]) -> VNRecognizeTextRequest {
    let r = VNRecognizeTextRequest()
    r.recognitionLevel = .accurate
    r.usesLanguageCorrection = true
    if !languages.isEmpty { r.recognitionLanguages = languages }
    return r
}

var args = Array(CommandLine.arguments.dropFirst())
let v = ProcessInfo.processInfo.operatingSystemVersion
let macos = "\(v.majorVersion).\(v.minorVersion).\(v.patchVersion)"
if args.first == "--list-languages" {
    let langs = (try? request([]).supportedRecognitionLanguages()) ?? []
    emit(["macos": macos, "revision": VNRecognizeTextRequest().revision, "languages": langs])
    exit(0)
}
var languages: [String] = []
if args.first == "--languages", args.count >= 2 {
    languages = args[1].split(separator: ",").map(String.init)
    args.removeFirst(2)
}

var images: [[String: Any]] = []
for path in args {
    let url = URL(fileURLWithPath: path)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(src, 0, nil) else { fail("cannot read \(path)") }
    let req = request(languages)
    do { try VNImageRequestHandler(cgImage: image, options: [:]).perform([req]) } catch { fail("\(error)") }
    var obs: [[String: Any]] = []
    for o in req.results ?? [] {
        guard let top = o.topCandidates(1).first else { continue }
        let s = top.string
        var words: [[String: Any]] = []
        var start: String.Index? = nil
        var i = s.startIndex
        func close(_ end: String.Index) {
            guard let st = start else { return }
            let r = (try? top.boundingBox(for: st..<end))??.boundingBox
            words.append(["text": String(s[st..<end]), "box": r.map(box) ?? NSNull()])
            start = nil
        }
        while i < s.endIndex {
            if s[i] == " " { close(i) } else if start == nil { start = i }
            i = s.index(after: i)
        }
        close(s.endIndex)
        var chars: [[String: Any]] = []
        var j = s.startIndex
        while j < s.endIndex {
            let k = s.index(after: j)
            if s[j] != " " {
                let r = (try? top.boundingBox(for: j..<k))??.boundingBox
                chars.append(["text": String(s[j..<k]), "box": r.map(box) ?? NSNull()])
            }
            j = k
        }
        obs.append(["string": s, "confidence": (Double(top.confidence) * 1000).rounded() / 1000,
                    "box": box(o.boundingBox), "words": words, "chars": chars])
    }
    images.append(["image": url.lastPathComponent, "width": image.width, "height": image.height, "observations": obs])
}
emit(["macos": macos, "request": "VNRecognizeTextRequest", "revision": VNRecognizeTextRequest().revision,
      "recognition_level": "accurate", "language_correction": true, "languages": languages, "images": images])
