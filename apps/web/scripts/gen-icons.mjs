// Generate simple solid-color PNG app icons with an "F" glyph so the PWA has
// real maskable icons without adding an image dependency. Uses only Node's
// zlib to emit a valid 8-bit RGBA PNG.
import { deflateSync } from 'node:zlib'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = join(here, '..', 'public', 'icons')
mkdirSync(outDir, { recursive: true })

const BG = [31, 41, 55, 255] // #1f2937
const FG = [255, 255, 255, 255]

// 7x7 bitmap of the letter F (1 = foreground).
const GLYPH = [
  '1111111',
  '1111111',
  '1100000',
  '1111100',
  '1111100',
  '1100000',
  '1100000',
]

function crc32(buf) {
  let c = ~0
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i]
    for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1
  }
  return (~c) >>> 0
}

function chunk(type, data) {
  const typeBuf = Buffer.from(type, 'ascii')
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length, 0)
  const crcBuf = Buffer.alloc(4)
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0)
  return Buffer.concat([len, typeBuf, data, crcBuf])
}

function makePng(size) {
  const raw = Buffer.alloc(size * (size * 4 + 1))
  const cell = size / 9 // 1-cell margin around a 7x7 glyph
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0 // filter byte
    for (let x = 0; x < size; x++) {
      const gx = Math.floor(x / cell) - 1
      const gy = Math.floor(y / cell) - 1
      const on =
        gy >= 0 && gy < 7 && gx >= 0 && gx < 7 && GLYPH[gy][gx] === '1'
      const color = on ? FG : BG
      const off = y * (size * 4 + 1) + 1 + x * 4
      raw[off] = color[0]
      raw[off + 1] = color[1]
      raw[off + 2] = color[2]
      raw[off + 3] = color[3]
    }
  }
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 6 // RGBA
  const idat = deflateSync(raw)
  return Buffer.concat([
    sig,
    chunk('IHDR', ihdr),
    chunk('IDAT', idat),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

for (const size of [192, 512]) {
  writeFileSync(join(outDir, `icon-${size}.png`), makePng(size))
  console.log(`wrote icon-${size}.png`)
}
