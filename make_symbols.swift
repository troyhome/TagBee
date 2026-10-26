// Saves the SF Symbols TagBee uses as white PNGs in icons/ (the app recolours them to match the theme).
// The same icon set MacBee uses. Usage: swift make_symbols.swift
import AppKit

let symbols = [
    "doc.badge.plus", "folder.badge.plus", "person.3", "list.number", "character.cursor.ibeam",
    "minus.circle", "trash", "square.and.arrow.down", "arrow.down.to.line", "photo", "xmark.circle.fill",
    "checkmark", "arrow.uturn.backward", "music.note.list", "folder", "checkmark.circle", "circle",
    "sidebar.left", "chevron.down", "chevron.right", "opticaldisc", "magnifyingglass", "wand.and.stars", "square.on.square", "text.quote", "waveform",
]
let canvas: CGFloat = 128  // square image; every symbol drawn at the same size (like letters), centred

try? FileManager.default.createDirectory(atPath: "icons", withIntermediateDirectories: true)
for name in symbols {
    let config = NSImage.SymbolConfiguration(pointSize: 64, weight: .regular)
    guard let symbol = NSImage(systemSymbolName: name, accessibilityDescription: nil)?.withSymbolConfiguration(config) else {
        print("missing symbol: \(name)"); continue
    }
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(canvas), pixelsHigh: Int(canvas), bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let s = symbol.size
    let scale = min(1, canvas / s.width, canvas / s.height)   // shrink only if a symbol would not fit
    let rect = NSRect(x: (canvas - s.width * scale) / 2, y: (canvas - s.height * scale) / 2,
                      width: s.width * scale, height: s.height * scale)
    symbol.draw(in: rect)
    NSColor.white.set()
    rect.insetBy(dx: -2, dy: -2).fill(using: .sourceAtop)   // paint the symbol white, keep its shape
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "icons/\(name).png"))
}
print("wrote \(symbols.count) icons to icons/")
