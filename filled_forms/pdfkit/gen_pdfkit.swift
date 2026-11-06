// Adds form widgets to an existing one-page PDF with macOS PDFKit and writes the result with
// PDFDocument.write, so the output file is PDFKit's own serialization.
//
// Usage:  gen_pdfkit <in.pdf> <out.pdf> <widgets.json>
// widgets.json is a list of objects:
//   {"name": "...", "kind": "text" | "checkbox", "rect": [x0, y0, x1, y1],
//    "value": "...", "state": "on" | "off", "background": "black" | "grey"}
// Rectangles are PDF points, bottom-left origin. Text widgets use Helvetica 11.
//
// Build:  swiftc -O -o gen_pdfkit gen_pdfkit.swift

import AppKit
import Foundation
import PDFKit

struct WidgetSpec: Decodable {
    let name: String
    let kind: String
    let rect: [Double]
    let value: String?
    let state: String?
    let background: String?
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write("gen_pdfkit: \(message)\n".data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count == 4 else { fail("usage: gen_pdfkit <in.pdf> <out.pdf> <widgets.json>") }
guard let doc = PDFDocument(url: URL(fileURLWithPath: args[1])), let page = doc.page(at: 0) else {
    fail("cannot open \(args[1])")
}
guard let json = FileManager.default.contents(atPath: args[3]),
      let specs = try? JSONDecoder().decode([WidgetSpec].self, from: json) else {
    fail("cannot read \(args[3])")
}

for s in specs {
    guard s.rect.count == 4 else { fail("bad rect for \(s.name)") }
    let r = CGRect(x: s.rect[0], y: s.rect[1], width: s.rect[2] - s.rect[0], height: s.rect[3] - s.rect[1])
    let w = PDFAnnotation(bounds: r, forType: .widget, withProperties: nil)
    w.fieldName = s.name
    w.backgroundColor = s.background == "black" ? .black : NSColor(white: 0.95, alpha: 1)
    switch s.kind {
    case "text":
        w.widgetFieldType = .text
        w.font = NSFont(name: "Helvetica", size: 11)
        w.fontColor = .black
        w.widgetStringValue = s.value ?? ""
    case "checkbox":
        w.widgetFieldType = .button
        w.widgetControlType = .checkBoxControl
        w.buttonWidgetState = s.state == "on" ? .onState : .offState
    default:
        fail("unknown kind \(s.kind)")
    }
    page.addAnnotation(w)
}

guard doc.write(to: URL(fileURLWithPath: args[2])) else { fail("write failed: \(args[2])") }
