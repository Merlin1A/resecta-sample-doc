// Writes one PDF page with macOS Core Text: each line is laid out by Core Text (shaping, bidi,
// vertical forms) in a font loaded from a given file, and drawn into a CGPDFContext, which embeds
// the glyphs it uses with a ToUnicode map.
//
// Usage:  ct_page <spec.json> <out.pdf>
// spec.json:
//   {"page": [w, h],
//    "lines": [{"runs": [{"text": "...", "font": "<path to .ttf>"}, ...], "size": 13,
//               "x": 72, "y": 700,            // left edge and baseline (PDF points, bottom-left origin)
//               "align": "left" | "right",    // "right": x is the right edge
//               "vertical": false}],          // true: a vertical column whose top is at (x, y)
//    "rules": [[x0, y0, x1, y1], ...]}       // thin filled rectangles (form lines)
//
// Build:  swiftc -O -o ct_page ct_page.swift

import CoreGraphics
import CoreText
import Foundation

struct Run: Decodable {
    let text: String
    let font: String
}

struct Line: Decodable {
    let runs: [Run]
    let size: Double
    let x: Double
    let y: Double
    let align: String?
    let vertical: Bool?
}

struct Spec: Decodable {
    let page: [Double]
    let lines: [Line]
    let rules: [[Double]]?
}

func fail(_ m: String) -> Never {
    FileHandle.standardError.write("ct_page: \(m)\n".data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count == 3 else { fail("usage: ct_page <spec.json> <out.pdf>") }
guard let data = FileManager.default.contents(atPath: args[1]),
      let spec = try? JSONDecoder().decode(Spec.self, from: data) else { fail("cannot read \(args[1])") }

var fonts: [String: CTFont] = [:]
func font(_ path: String, _ size: Double) -> CTFont {
    let key = "\(path)@\(size)"
    if let f = fonts[key] { return f }
    guard let provider = CGDataProvider(filename: path), let cg = CGFont(provider) else { fail("cannot load \(path)") }
    let f = CTFontCreateWithGraphicsFont(cg, CGFloat(size), nil, nil)
    fonts[key] = f
    return f
}

var box = CGRect(x: 0, y: 0, width: spec.page[0], height: spec.page[1])
let out = NSMutableData()
let info: [CFString: Any] = [kCGPDFContextCreator: "ct_page (Core Text)", kCGPDFContextTitle: "Synthetic script fixture"]
guard let consumer = CGDataConsumer(data: out as CFMutableData),
      let ctx = CGContext(consumer: consumer, mediaBox: &box, info as CFDictionary) else { fail("cannot open a PDF context") }
ctx.beginPDFPage(nil)
ctx.setFillColor(CGColor(gray: 0, alpha: 1))
for r in spec.rules ?? [] {
    ctx.fill(CGRect(x: r[0], y: r[1], width: r[2] - r[0], height: r[3] - r[1]))
}
func attributed(_ line: Line) -> NSAttributedString {
    let out = NSMutableAttributedString()
    for run in line.runs {
        var attrs: [NSAttributedString.Key: Any] = [
            NSAttributedString.Key(kCTFontAttributeName as String): font(run.font, line.size),
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 0, alpha: 1),
        ]
        if line.vertical == true {
            attrs[NSAttributedString.Key(kCTVerticalFormsAttributeName as String)] = true
        }
        out.append(NSAttributedString(string: run.text, attributes: attrs))
    }
    return out
}

for line in spec.lines {
    if line.vertical == true {
        let s = attributed(line)
        let setter = CTFramesetterCreateWithAttributedString(s)
        let width = line.size * 1.6
        let height = line.y - 72
        let rect = CGRect(x: line.x - width / 2, y: line.y - height, width: width, height: height)
        let frameAttrs = [kCTFrameProgressionAttributeName: CTFrameProgression.rightToLeft.rawValue] as CFDictionary
        let frame = CTFramesetterCreateFrame(setter, CFRange(location: 0, length: 0), CGPath(rect: rect, transform: nil), frameAttrs)
        CTFrameDraw(frame, ctx)
        continue
    }
    let ct = CTLineCreateWithAttributedString(attributed(line))
    let width = CTLineGetTypographicBounds(ct, nil, nil, nil)
    let x = line.align == "right" ? line.x - width : line.x
    ctx.textPosition = CGPoint(x: x, y: line.y)
    CTLineDraw(ct, ctx)
}
ctx.endPDFPage()
ctx.closePDF()
guard out.write(toFile: args[2], atomically: true) else { fail("cannot write \(args[2])") }
