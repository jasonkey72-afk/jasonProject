/*
 * pptx.js - 수집한 본문을 PowerPoint 파일(.pptx)로 만든다.
 *
 * .pptx 는 XML 여러 개를 담은 ZIP 파일이다. 확장 프로그램에는 외부 라이브러리를
 * 넣을 수 없으므로(브라우저 보안 정책), ZIP 압축과 PresentationML 문서를 직접 만든다.
 *
 * 슬라이드 구성
 *   - 문서마다 표지(제목/출처/수집 시각)
 *   - 제목(##, ###) 단위로 내용 슬라이드, 길면 자동으로 다음 장에 이어짐
 *   - 표는 표 개체로, 그림은 한 장에 하나씩 (설명은 아래에)
 */
'use strict';

/* ---------------------------------------------------------------- */
/* ZIP 만들기                                                        */
/* ---------------------------------------------------------------- */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

async function deflateRaw(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function dosDateTime(date) {
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
  const day = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { time, day };
}

/**
 * ZIP 파일을 만든다.
 * @param {{name:string, data:Uint8Array}[]} entries
 */
async function makeZip(entries) {
  const encoder = new TextEncoder();
  const { time, day } = dosDateTime(new Date());
  const parts = [];
  const central = [];
  let offset = 0;

  for (const entry of entries) {
    const name = encoder.encode(entry.name);
    const raw = entry.data;
    const packed = await deflateRaw(raw);
    const deflated = packed.length < raw.length;
    const body = deflated ? packed : raw;
    const crc = crc32(raw);

    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);            // 필요 버전
    local.setUint16(6, 0, true);             // 플래그
    local.setUint16(8, deflated ? 8 : 0, true);
    local.setUint16(10, time, true);
    local.setUint16(12, day, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, body.length, true);
    local.setUint32(22, raw.length, true);
    local.setUint16(26, name.length, true);
    local.setUint16(28, 0, true);

    parts.push(new Uint8Array(local.buffer), name, body);

    const dir = new DataView(new ArrayBuffer(46));
    dir.setUint32(0, 0x02014b50, true);
    dir.setUint16(4, 20, true);              // 만든 버전
    dir.setUint16(6, 20, true);              // 필요 버전
    dir.setUint16(8, 0, true);
    dir.setUint16(10, deflated ? 8 : 0, true);
    dir.setUint16(12, time, true);
    dir.setUint16(14, day, true);
    dir.setUint32(16, crc, true);
    dir.setUint32(20, body.length, true);
    dir.setUint32(24, raw.length, true);
    dir.setUint16(28, name.length, true);
    dir.setUint32(42, offset, true);
    central.push(new Uint8Array(dir.buffer), name);

    offset += 30 + name.length + body.length;
  }

  const centralSize = central.reduce((n, part) => n + part.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, entries.length, true);
  end.setUint16(10, entries.length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);

  const all = [...parts, ...central, new Uint8Array(end.buffer)];
  const total = all.reduce((n, part) => n + part.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of all) { out.set(part, at); at += part.length; }
  return out;
}

/* ---------------------------------------------------------------- */
/* 슬라이드 크기와 서식                                              */
/* ---------------------------------------------------------------- */

const EMU = 914400;                       // 1인치
const SLIDE_W = 12192000;                 // 13.333인치 (16:9)
const SLIDE_H = 6858000;                  // 7.5인치
const MARGIN = Math.round(0.7 * EMU);
const BODY_TOP = Math.round(1.75 * EMU);
const BODY_W = SLIDE_W - MARGIN * 2;
const BODY_H = SLIDE_H - BODY_TOP - Math.round(0.6 * EMU);

const FONT = '맑은 고딕';
const FONT_MONO = 'Consolas';
const NAVY = '1F3864';
const INK = '1B1B1B';
const MUTED = '5A6472';

const MAX_LINES = 12;                     // 한 장에 넣을 최대 줄 수
const CHARS_PER_LINE = 44;                // 18pt 기준 한 줄에 들어가는 글자 폭
const MAX_SLIDES_PER_DOC = 80;

function esc(text) {
  return String(text == null ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&apos;')
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '');
}

/** 한글은 한 글자를 1, 영문·숫자는 0.5 로 세어 줄 수를 어림한다. */
function visualWidth(text) {
  let width = 0;
  for (const ch of String(text)) width += /[\x20-\x7E]/.test(ch) ? 0.5 : 1;
  return width;
}

const lineCount = (text) => Math.max(1, Math.ceil(visualWidth(text) / CHARS_PER_LINE));

/* ---------------------------------------------------------------- */
/* 마크다운 -> 블록                                                  */
/* ---------------------------------------------------------------- */

function stripInline(text) {
  return String(text)
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/(^|[^\\])\*([^*\n]+)\*/g, '$1$2')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\\([*_`])/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

function parseBlocks(markdown) {
  const blocks = [];
  const lines = String(markdown || '').split('\n');
  let code = null;
  let table = null;

  const flushTable = () => {
    if (table && table.length) blocks.push({ type: 'table', rows: table });
    table = null;
  };

  for (const raw of lines) {
    if (/^\s*```/.test(raw)) {
      if (code) { blocks.push({ type: 'code', lines: code }); code = null; }
      else { flushTable(); code = []; }
      continue;
    }
    if (code) { code.push(raw); continue; }

    const line = raw.trim();

    if (/^\|/.test(line)) {
      if (/^\|[\s|:-]+$/.test(line)) continue;           // 표 구분선
      const cells = line.replace(/^\|/, '').replace(/\|$/, '')
        .split('|').map((c) => stripInline(c.replace(/\\\|/g, '|')));
      (table = table || []).push(cells);
      continue;
    }
    flushTable();

    if (!line || /^---+$/.test(line)) continue;

    const image = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
    if (image) { blocks.push({ type: 'image', alt: image[1], src: image[2] }); continue; }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const text = stripInline(heading[2]);
      if (text) blocks.push({ type: 'heading', level: heading[1].length, text });
      continue;
    }

    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      const text = stripInline(quote[1]);
      if (text) blocks.push({ type: 'quote', text });
      continue;
    }

    const indent = Math.floor((raw.match(/^ */)[0].length) / 2);
    const bullet = line.match(/^[-*]\s+(.*)$/);
    if (bullet) {
      const text = stripInline(bullet[1]);
      if (text) blocks.push({ type: 'bullet', indent, text });
      continue;
    }
    const numbered = line.match(/^(\d+)\.\s+(.*)$/);
    if (numbered) {
      const text = stripInline(numbered[2]);
      if (text) blocks.push({ type: 'bullet', indent, text, number: numbered[1] });
      continue;
    }

    // 문단 안에 들어 있는 그림도 따로 뽑아 준다.
    let match;
    const imageInline = /!\[([^\]]*)\]\((data:[^)]+|https?:[^)]+)\)/g;
    while ((match = imageInline.exec(raw)) !== null) {
      blocks.push({ type: 'image', alt: match[1], src: match[2] });
    }
    const text = stripInline(line);
    if (text) blocks.push({ type: 'para', text });
  }

  if (code) blocks.push({ type: 'code', lines: code });
  flushTable();
  return blocks;
}

/* ---------------------------------------------------------------- */
/* 블록 -> 슬라이드 구성                                             */
/* ---------------------------------------------------------------- */

function planSlides(item, humanTime) {
  const slides = [{
    kind: 'cover',
    title: item.title,
    lines: [`출처: ${item.url}`, `수집 시각: ${humanTime(item.capturedAt)}`]
  }];

  const blocks = parseBlocks(item.markdown);
  let title = item.title;
  let body = [];
  let part = 0;
  let captionOf = '';   // 그림 슬라이드에 이미 넣은 설명 (바로 뒤 같은 문장은 중복이라 건너뛴다)

  const flush = () => {
    if (!body.length) return;
    part += 1;
    slides.push({ kind: 'body', title: part > 1 ? `${title} (${part})` : title, body });
    body = [];
  };

  const push = (entry, weight) => {
    const used = body.reduce((n, b) => n + b.weight, 0);
    if (used + weight > MAX_LINES && body.length) flush();
    body.push({ ...entry, weight });
  };

  for (const block of blocks) {
    if (slides.length >= MAX_SLIDES_PER_DOC) {
      slides.push({ kind: 'body', title: '(이하 생략)', body: [{ type: 'para', text: '내용이 많아 이후 부분은 넣지 않았습니다. 전체 내용은 Markdown/PDF 형식으로 저장해 주세요.', weight: 2 }] });
      return slides;
    }

    if (block.type !== 'image' && block.type !== 'para') captionOf = '';

    switch (block.type) {
      case 'heading':
        flush();
        title = block.text;
        part = 0;
        break;

      case 'image':
        flush();
        slides.push({ kind: 'image', title, alt: block.alt, src: block.src });
        captionOf = block.alt ? block.alt.replace(/\s+/g, '') : '';
        continue;

      case 'table': {
        flush();
        slides.push({ kind: 'table', title, rows: block.rows });
        break;
      }

      case 'code':
        push({ type: 'code', lines: block.lines }, Math.min(block.lines.length + 1, MAX_LINES));
        break;

      case 'bullet':
        push({ type: 'bullet', indent: block.indent, text: block.text, number: block.number },
          lineCount(block.text));
        break;

      case 'quote':
        push({ type: 'quote', text: block.text }, lineCount(block.text));
        break;

      default: {
        // 그림 바로 아래의 설명(figcaption)은 그림 슬라이드에 이미 들어갔다.
        const compact = block.text.replace(/\s+/g, '');
        if (captionOf && compact.includes(captionOf)) break;
        push({ type: 'para', text: block.text }, lineCount(block.text) + 0.3);
      }
    }
  }
  flush();
  return slides;
}

/* ---------------------------------------------------------------- */
/* 슬라이드 XML                                                      */
/* ---------------------------------------------------------------- */

const XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
const NS_P = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
  + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
  + 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"';

function runProps(opts = {}) {
  const attrs = [`lang="ko-KR"`, `altLang="en-US"`, `sz="${opts.size || 1800}"`,
    `b="${opts.bold ? 1 : 0}"`, `dirty="0"`].join(' ');
  return `<a:rPr ${attrs}><a:solidFill><a:srgbClr val="${opts.color || INK}"/></a:solidFill>`
    + `<a:latin typeface="${opts.mono ? FONT_MONO : FONT}"/><a:ea typeface="${opts.mono ? FONT_MONO : FONT}"/></a:rPr>`;
}

function paragraph(text, opts = {}) {
  const props = [];
  if (opts.indent) props.push(`marL="${opts.indent * 285750 + 285750}" lvl="${Math.min(opts.indent, 4)}"`);
  else if (opts.bullet) props.push('marL="285750" indent="-285750"');
  if (opts.align) props.push(`algn="${opts.align}"`);
  const spacing = `<a:spcBef><a:spcPts val="${opts.spaceBefore == null ? 400 : opts.spaceBefore}"/></a:spcBef>`;
  const bullet = opts.bullet
    ? (opts.number
      ? `<a:buFont typeface="Arial"/><a:buAutoNum type="arabicPeriod"/>`
      : `<a:buFont typeface="Arial"/><a:buChar char="•"/>`)
    : '<a:buNone/>';
  const pPr = `<a:pPr ${props.join(' ')}>${spacing}${bullet}</a:pPr>`;
  const runs = text
    ? `<a:r>${runProps(opts)}<a:t>${esc(text)}</a:t></a:r>`
    : `<a:endParaRPr lang="ko-KR"/>`;
  return `<a:p>${pPr}${runs}</a:p>`;
}

function textBox(id, name, x, y, cx, cy, paragraphs, opts = {}) {
  return `<p:sp><p:nvSpPr><p:cNvPr id="${id}" name="${esc(name)}"/>`
    + `<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>`
    + `<p:spPr><a:xfrm><a:off x="${x}" y="${y}"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm>`
    + `<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>`
    + `<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="${opts.anchor || 't'}">`
    + `<a:normAutofit/></a:bodyPr><a:lstStyle/>${paragraphs.join('')}</p:txBody></p:sp>`;
}

function pictureShape(id, relId, x, y, cx, cy) {
  return `<p:pic><p:nvPicPr><p:cNvPr id="${id}" name="그림 ${id}"/>`
    + `<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>`
    + `<p:blipFill><a:blip r:embed="${relId}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>`
    + `<p:spPr><a:xfrm><a:off x="${x}" y="${y}"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm>`
    + `<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>`;
}

function tableCell(text, opts = {}) {
  const fill = opts.header ? `<a:solidFill><a:srgbClr val="E9EEF7"/></a:solidFill>` : '<a:noFill/>';
  const border = (tag) => `<a:${tag} w="6350" cap="flat"><a:solidFill><a:srgbClr val="9AA5B5"/></a:solidFill></a:${tag}>`;
  return `<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>`
    + paragraph(text, { size: 1300, bold: !!opts.header, spaceBefore: 0 })
    + `</a:txBody><a:tcPr marL="68580" marR="68580" marT="45720" marB="45720" anchor="ctr">`
    + border('lnL') + border('lnR') + border('lnT') + border('lnB') + fill + `</a:tcPr></a:tc>`;
}

function tableShape(id, rows, x, y, cx) {
  const columns = Math.max(...rows.map((r) => r.length));
  const colWidth = Math.floor(cx / columns);
  const rowHeight = 370840;
  const grid = new Array(columns).fill(`<a:gridCol w="${colWidth}"/>`).join('');
  const body = rows.map((cells, index) => {
    const filled = cells.slice();
    while (filled.length < columns) filled.push('');
    return `<a:tr h="${rowHeight}">`
      + filled.map((c) => tableCell(c, { header: index === 0 })).join('')
      + `</a:tr>`;
  }).join('');

  return `<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="${id}" name="표 ${id}"/>`
    + `<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>`
    + `<p:xfrm><a:off x="${x}" y="${y}"/><a:ext cx="${colWidth * columns}" cy="${rowHeight * rows.length}"/></p:xfrm>`
    + `<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">`
    + `<a:tbl><a:tblPr firstRow="1"/><a:tblGrid>${grid}</a:tblGrid>${body}</a:tbl>`
    + `</a:graphicData></a:graphic></p:graphicFrame>`;
}

function slideXml(shapes, opts = {}) {
  const background = opts.dark
    ? `<p:bg><p:bgPr><a:solidFill><a:srgbClr val="${NAVY}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>`
    : '';
  return XML_HEAD + `<p:sld ${NS_P}><p:cSld>${background}<p:spTree>`
    + `<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>`
    + `<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>`
    + `<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>`
    + shapes.join('')
    + `</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>`;
}

/* ---------------------------------------------------------------- */
/* 고정 부품 (테마 / 슬라이드 마스터 / 레이아웃)                      */
/* ---------------------------------------------------------------- */

function themeXml() {
  const colors = ['dk1:sysClr:windowText', 'lt1:sysClr:window', 'dk2:srgbClr:44546A', 'lt2:srgbClr:E7E6E6',
    'accent1:srgbClr:2D6CDF', 'accent2:srgbClr:1F3864', 'accent3:srgbClr:70AD47', 'accent4:srgbClr:FFC000',
    'accent5:srgbClr:5B9BD5', 'accent6:srgbClr:A5A5A5', 'hlink:srgbClr:0563C1', 'folHlink:srgbClr:954F72']
    .map((entry) => {
      const [name, kind, value] = entry.split(':');
      const inner = kind === 'sysClr'
        ? `<a:sysClr val="${value}" lastClr="${value === 'windowText' ? '000000' : 'FFFFFF'}"/>`
        : `<a:srgbClr val="${value}"/>`;
      return `<a:${name}>${inner}</a:${name}>`;
    }).join('');

  const fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>';
  const line = '<a:ln w="9525" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    + '<a:prstDash val="solid"/></a:ln>';
  const effect = '<a:effectStyle><a:effectLst/></a:effectStyle>';

  return XML_HEAD
    + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="웹문서화">'
    + `<a:themeElements><a:clrScheme name="웹문서화">${colors}</a:clrScheme>`
    + `<a:fontScheme name="웹문서화">`
    + `<a:majorFont><a:latin typeface="${FONT}"/><a:ea typeface="${FONT}"/><a:cs typeface=""/></a:majorFont>`
    + `<a:minorFont><a:latin typeface="${FONT}"/><a:ea typeface="${FONT}"/><a:cs typeface=""/></a:minorFont>`
    + `</a:fontScheme>`
    + `<a:fmtScheme name="웹문서화">`
    + `<a:fillStyleLst>${fill}${fill}${fill}</a:fillStyleLst>`
    + `<a:lnStyleLst>${line}${line}${line}</a:lnStyleLst>`
    + `<a:effectStyleLst>${effect}${effect}${effect}</a:effectStyleLst>`
    + `<a:bgFillStyleLst>${fill}${fill}${fill}</a:bgFillStyleLst>`
    + `</a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>`;
}

const EMPTY_TREE = `<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>`
  + `<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>`
  + `<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree>`;

function slideMasterXml() {
  const clrMap = '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2"'
    + ' accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>';
  return XML_HEAD + `<p:sldMaster ${NS_P}><p:cSld>`
    + `<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>${EMPTY_TREE}</p:cSld>`
    + clrMap
    + `<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>`
    + `<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>`;
}

function slideLayoutXml() {
  return XML_HEAD + `<p:sldLayout ${NS_P} type="blank" preserve="1">`
    + `<p:cSld name="빈 화면">${EMPTY_TREE}</p:cSld>`
    + `<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>`;
}

function presentationXml(slideCount) {
  const ids = Array.from({ length: slideCount },
    (_, i) => `<p:sldId id="${256 + i}" r:id="rId${i + 2}"/>`).join('');
  return XML_HEAD + `<p:presentation ${NS_P} saveSubsetFonts="1">`
    + `<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>`
    + `<p:sldIdLst>${ids}</p:sldIdLst>`
    + `<p:sldSz cx="${SLIDE_W}" cy="${SLIDE_H}"/><p:notesSz cx="${SLIDE_H}" cy="${SLIDE_W}"/>`
    + `<p:defaultTextStyle/></p:presentation>`;
}

function relsXml(entries) {
  const items = entries.map((e) => `<Relationship Id="${e.id}" Type="${e.type}" Target="${e.target}"/>`).join('');
  return XML_HEAD
    + `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${items}</Relationships>`;
}

const REL = {
  officeDoc: 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument',
  master: 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster',
  layout: 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout',
  slide: 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide',
  theme: 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme',
  image: 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image',
  core: 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties',
  app: 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties'
};

function contentTypesXml(slideCount, imageExts) {
  const defaults = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
    '<Default Extension="xml" ContentType="application/xml"/>']
    .concat(Array.from(imageExts).map((ext) => {
      const type = ext === 'png' ? 'image/png' : ext === 'gif' ? 'image/gif'
        : ext === 'svg' ? 'image/svg+xml' : 'image/jpeg';
      return `<Default Extension="${ext}" ContentType="${type}"/>`;
    })).join('');

  const slides = Array.from({ length: slideCount }, (_, i) =>
    `<Override PartName="/ppt/slides/slide${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>`
  ).join('');

  return XML_HEAD
    + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    + defaults
    + '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
    + '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
    + '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
    + '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
    + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    + '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    + slides + '</Types>';
}

function corePropsXml(title) {
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  return XML_HEAD
    + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
    + ' xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"'
    + ' xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    + `<dc:title>${esc(title)}</dc:title><dc:creator>웹 본문 문서화 도구</dc:creator>`
    + `<cp:lastModifiedBy>웹 본문 문서화 도구</cp:lastModifiedBy>`
    + `<dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created>`
    + `<dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified></cp:coreProperties>`;
}

function appPropsXml(slideCount) {
  return XML_HEAD
    + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
    + ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    + `<Application>웹 본문 문서화 도구</Application><Slides>${slideCount}</Slides>`
    + '<ScaleCrop>false</ScaleCrop><LinksUpToDate>false</LinksUpToDate>'
    + '<SharedDoc>false</SharedDoc><HyperlinksChanged>false</HyperlinksChanged></Properties>';
}

/* ---------------------------------------------------------------- */
/* 그림                                                              */
/* ---------------------------------------------------------------- */

function dataUrlToBytes(dataUrl) {
  const comma = dataUrl.indexOf(',');
  const meta = dataUrl.slice(0, comma);
  const body = dataUrl.slice(comma + 1);
  const binary = atob(body);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const mime = (meta.match(/^data:([^;,]+)/) || [])[1] || 'image/png';
  return { bytes, mime };
}

const EXT_BY_MIME = { 'image/png': 'png', 'image/jpeg': 'jpeg', 'image/jpg': 'jpeg', 'image/gif': 'gif' };

async function imageSize(bytes, mime) {
  try {
    const bitmap = await createImageBitmap(new Blob([bytes], { type: mime }));
    const size = { width: bitmap.width, height: bitmap.height };
    bitmap.close();
    return size;
  } catch (_) {
    return { width: 800, height: 600 };
  }
}

/* ---------------------------------------------------------------- */
/* 전체 조립                                                         */
/* ---------------------------------------------------------------- */

/**
 * 수집 항목들을 .pptx 파일 내용(Uint8Array)으로 만든다.
 * @param {object[]} items
 * @param {string} mergedTitle 여러 건을 한 파일로 만들 때의 표지 제목 ('' 이면 한 건)
 * @param {(iso:string)=>string} humanTime 날짜 표기 함수
 */
async function buildPptx(items, mergedTitle, humanTime) {
  const media = [];        // {name, bytes, ext}
  const slides = [];       // {xml, rels:[{id, target}]}
  const imageExts = new Set(['png', 'jpeg']);

  const addImage = async (dataUrl) => {
    if (!/^data:image\//i.test(dataUrl)) return null; // 주소만 있는 그림은 넣을 수 없다
    const { bytes, mime } = dataUrlToBytes(dataUrl);
    const ext = EXT_BY_MIME[mime] || 'png';
    imageExts.add(ext);
    const name = `image${media.length + 1}.${ext}`;
    media.push({ name, bytes, ext });
    return { name, size: await imageSize(bytes, mime) };
  };

  const titleBox = (text, opts = {}) => textBox(2, '제목', MARGIN, opts.y == null ? Math.round(0.6 * EMU) : opts.y,
    BODY_W, Math.round(1 * EMU),
    [paragraph(text, { size: opts.size || 2800, bold: true, color: opts.color || NAVY, spaceBefore: 0 })],
    { anchor: 'ctr' });

  if (mergedTitle) {
    slides.push({
      rels: [],
      xml: slideXml([
        titleBox(mergedTitle, { size: 4000, color: 'FFFFFF', y: Math.round(2.4 * EMU) }),
        textBox(3, '설명', MARGIN, Math.round(3.7 * EMU), BODY_W, Math.round(1.2 * EMU), [
          paragraph(`총 ${items.length}건 · 저장 시각 ${humanTime(new Date().toISOString())}`,
            { size: 1600, color: 'C7D6F0', spaceBefore: 0 }),
          ...items.slice(0, 8).map((it, i) => paragraph(`${i + 1}. ${it.title}`, { size: 1400, color: 'E7EDF9' }))
        ])
      ], { dark: true })
    });
  }

  for (const item of items) {
    for (const plan of planSlides(item, humanTime)) {
      if (plan.kind === 'cover') {
        slides.push({
          rels: [],
          xml: slideXml([
            titleBox(plan.title, { size: 3600, color: 'FFFFFF', y: Math.round(2.5 * EMU) }),
            textBox(3, '출처', MARGIN, Math.round(4.1 * EMU), BODY_W, Math.round(1 * EMU),
              plan.lines.map((line) => paragraph(line, { size: 1400, color: 'C7D6F0', spaceBefore: 200 })))
          ], { dark: true })
        });
        continue;
      }

      if (plan.kind === 'image') {
        const image = await addImage(plan.src);
        if (!image) continue;
        const boxH = BODY_H - Math.round(0.5 * EMU);
        const naturalW = image.size.width * 9525;
        const naturalH = image.size.height * 9525;
        const scale = Math.min(BODY_W / naturalW, boxH / naturalH, 1);
        const cx = Math.round(naturalW * scale);
        const cy = Math.round(naturalH * scale);
        const relId = 'rId1';
        slides.push({
          rels: [{ id: relId, target: `../media/${image.name}` }],
          xml: slideXml([
            titleBox(plan.title),
            pictureShape(4, relId, Math.round((SLIDE_W - cx) / 2), BODY_TOP, cx, cy),
            textBox(5, '설명', MARGIN, BODY_TOP + cy + Math.round(0.15 * EMU), BODY_W, Math.round(0.4 * EMU),
              [paragraph(plan.alt || '', { size: 1200, color: MUTED, align: 'ctr', spaceBefore: 0 })])
          ])
        });
        continue;
      }

      if (plan.kind === 'table') {
        slides.push({
          rels: [],
          xml: slideXml([titleBox(plan.title), tableShape(4, plan.rows, MARGIN, BODY_TOP, BODY_W)])
        });
        continue;
      }

      const paragraphs = [];
      for (const entry of plan.body) {
        if (entry.type === 'code') {
          entry.lines.forEach((line) => paragraphs.push(
            paragraph(line, { size: 1400, mono: true, color: MUTED, spaceBefore: 0 })));
        } else if (entry.type === 'bullet') {
          paragraphs.push(paragraph(entry.text,
            { bullet: true, indent: entry.indent, number: entry.number, size: entry.indent ? 1600 : 1800 }));
        } else if (entry.type === 'quote') {
          paragraphs.push(paragraph(entry.text, { size: 1600, color: MUTED }));
        } else {
          paragraphs.push(paragraph(entry.text, { size: 1800 }));
        }
      }
      slides.push({
        rels: [],
        xml: slideXml([titleBox(plan.title), textBox(4, '본문', MARGIN, BODY_TOP, BODY_W, BODY_H, paragraphs)])
      });
    }
  }

  /* ---- 파일 묶기 ---- */
  const encoder = new TextEncoder();
  const files = [];
  const add = (name, text) => files.push({ name, data: encoder.encode(text) });

  add('_rels/.rels', relsXml([
    { id: 'rId1', type: REL.officeDoc, target: 'ppt/presentation.xml' },
    { id: 'rId2', type: REL.core, target: 'docProps/core.xml' },
    { id: 'rId3', type: REL.app, target: 'docProps/app.xml' }
  ]));
  add('docProps/core.xml', corePropsXml(mergedTitle || items[0].title));
  add('docProps/app.xml', appPropsXml(slides.length));
  add('ppt/presentation.xml', presentationXml(slides.length));
  add('ppt/_rels/presentation.xml.rels', relsXml([
    { id: 'rId1', type: REL.master, target: 'slideMasters/slideMaster1.xml' },
    ...slides.map((_, i) => ({ id: `rId${i + 2}`, type: REL.slide, target: `slides/slide${i + 1}.xml` })),
    { id: `rId${slides.length + 2}`, type: REL.theme, target: 'theme/theme1.xml' }
  ]));
  add('ppt/theme/theme1.xml', themeXml());
  add('ppt/slideMasters/slideMaster1.xml', slideMasterXml());
  add('ppt/slideMasters/_rels/slideMaster1.xml.rels', relsXml([
    { id: 'rId1', type: REL.layout, target: '../slideLayouts/slideLayout1.xml' },
    { id: 'rId2', type: REL.theme, target: '../theme/theme1.xml' }
  ]));
  add('ppt/slideLayouts/slideLayout1.xml', slideLayoutXml());
  add('ppt/slideLayouts/_rels/slideLayout1.xml.rels', relsXml([
    { id: 'rId1', type: REL.master, target: '../slideMasters/slideMaster1.xml' }
  ]));

  slides.forEach((slide, i) => {
    add(`ppt/slides/slide${i + 1}.xml`, slide.xml);
    add(`ppt/slides/_rels/slide${i + 1}.xml.rels`, relsXml([
      { id: 'rId100', type: REL.layout, target: '../slideLayouts/slideLayout1.xml' },
      ...slide.rels.map((rel) => ({ id: rel.id, type: REL.image, target: rel.target }))
    ]));
  });

  media.forEach((image) => files.push({ name: `ppt/media/${image.name}`, data: image.bytes }));

  // [Content_Types].xml 은 OPC 규약상 압축 파일의 첫 항목이어야 한다.
  // (뒤에 두면 PowerPoint·LibreOffice 가 파일을 열지 못한다)
  files.unshift({
    name: '[Content_Types].xml',
    data: encoder.encode(contentTypesXml(slides.length, imageExts))
  });

  return makeZip(files);
}
