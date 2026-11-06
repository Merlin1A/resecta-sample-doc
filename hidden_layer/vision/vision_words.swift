// Runs Apple's Vision text recognition (VNRecognizeTextRequest, accurate level, US English, language
// correction on) on each image given on the command line and prints one JSON document to stdout: the
// macOS version, the request revision, and per image every observation's top string with its
// confidence and box, and the box of each space-separated word in that string.
//
// Boxes are Vision's normalized image coordinates (0-1, bottom-left origin), printed to 6 decimals.
//
// Build:  swiftc -O -o vision_words vision_words.swift
// Run:    ./vision_words page1.jpg page2.jpg > out.json

import Foundation
import ImageIO
import Vision

func box(_ r: CGRect) -> [Double] {
    [r.minX, r.minY, r.maxX, r.maxY].map { (Double($0) * 1_000_000).rounded() / 1_000_000 }
}

func words(of text: String) -> [Range<String.Index>] {
    var out: [Range<String.Index>] = []
    var start: String.Index? = nil
    var i = text.startIndex
    while i < text.endIndex {
        if text[i] == " " {
            if let s = start { out.append(s..<i); start = nil }
        } else if start == nil {
            start = i
        }
        i = text.index(after: i)
    }
    if let s = start { out.append(s..<text.endIndex) }
    return out
}

func recognize(_ path: String) throws -> [String: Any] {
    let url = URL(fileURLWithPath: path)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        throw NSError(domain: "vision_words", code: 1, userInfo: [NSLocalizedDescriptionKey: "cannot read \(path)"])
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]
    request.usesLanguageCorrection = true
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    var observations: [[String: Any]] = []
    for obs in request.results ?? [] {
        guard let top = obs.topCandidates(1).first else { continue }
        var ws: [[String: Any]] = []
        for range in words(of: top.string) {
            let r = try top.boundingBox(for: range)?.boundingBox ?? .null
            ws.append(["text": String(top.string[range]), "box": r.isNull ? NSNull() : box(r)])
        }
        observations.append([
            "string": top.string,
            "confidence": (Double(top.confidence) * 1000).rounded() / 1000,
            "box": box(obs.boundingBox),
            "words": ws,
        ])
    }
    return [
        "image": url.lastPathComponent,
        "width": image.width,
        "height": image.height,
        "observations": observations,
    ]
}

let paths = Array(CommandLine.arguments.dropFirst())
var images: [[String: Any]] = []
for p in paths {
    do {
        images.append(try recognize(p))
    } catch {
        FileHandle.standardError.write("vision_words: \(error.localizedDescription)\n".data(using: .utf8)!)
        exit(1)
    }
}
let v = ProcessInfo.processInfo.operatingSystemVersion
let doc: [String: Any] = [
    "macos": "\(v.majorVersion).\(v.minorVersion).\(v.patchVersion)",
    "request": "VNRecognizeTextRequest",
    "revision": VNRecognizeTextRequest().revision,
    "recognition_level": "accurate",
    "languages": ["en-US"],
    "language_correction": true,
    "images": images,
]
let data = try JSONSerialization.data(withJSONObject: doc, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write("\n".data(using: .utf8)!)
