// One-page EDA note for Kwera Stella. Run: node docs/build_stella_note.js <out.docx>
const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
        BorderStyle, AlignmentType, LevelFormat } = require('docx');

const FONT = 'Arial', SIZE = 18;            // 9 pt
const W = 10466;                             // A4 width less 0.7" margins, in DXA
const run = (t, o = {}) => new TextRun({ text: t, font: FONT, size: SIZE, ...o });
const para = (parts, o = {}) => new Paragraph({ spacing: { after: 60 }, ...o,
  children: (Array.isArray(parts) ? parts : [parts]).map(p => typeof p === 'string' ? run(p) : p) });
const head = t => new Paragraph({ spacing: { before: 120, after: 50 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: '1F4E79', space: 1 } },
  children: [run(t, { bold: true, size: 21, color: '1F4E79' })] });
const bullet = parts => para(parts, { numbering: { reference: 'b', level: 0 }, spacing: { after: 40 } });
const b = t => run(t, { bold: true });

const border = { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' };
const borders = { top: border, bottom: border, left: border, right: border };
function table(widths, rows) {
  return new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((r, i) => new TableRow({ children: r.map((c, j) => new TableCell({
      width: { size: widths[j], type: WidthType.DXA }, borders,
      margins: { top: 25, bottom: 25, left: 70, right: 70 },
      shading: i === 0 ? { type: ShadingType.CLEAR, fill: 'DCE6F1', color: 'auto' } : undefined,
      children: [new Paragraph({ alignment: j > 0 && typeof c === 'number' ? AlignmentType.RIGHT : AlignmentType.LEFT,
        children: [run(typeof c === 'number' ? c.toLocaleString('en-US') : c, { size: 17, bold: i === 0 })] })] })) })) });
}

const issues = table([680, 4080, 1300, 1350, 3056], [
  ['Code', 'What we found', 'Declarations', 'Taxpayers', 'What the model does'],
  ['E01', 'Same entry under more than one declaration ID', 0, 0, 'Keeps the latest ID per entry (R14)'],
  ['E02', 'The same item row repeated', 7568, 154, 'Each item once (R5), vehicles out (R15)'],
  ['E03', 'TIN blank or not 10 digits', 0, 0, 'Scores 10-digit TINs only (R1)'],
  ['E04', 'Cancelled declarations', 9894, 1809, 'Left out (R3)'],
  ['E05', 'APC 483: destroyed or abandoned goods, dummy entries', 1582, 356, 'Left out (R13)'],
  ['E06', 'Top-up flag Y, but final tax not above original tax', 10087, 4919, 'Not a top-up (R7)'],
  ['E07', 'Tax rose, but no top-up flag', 7031, 1929, 'Not a top-up. Please confirm'],
  ['E08', 'Original tax blank', 'about 453,000', '972 in sample', 'Read as unchanged. Please confirm'],
  ['E09', 'top_up_amt holds the final tax when no top-up', 'about 628,000', '4,038 in sample', 'top_up_amt not used (R7)'],
  ['E11', 'Customs value or weight zero, negative or blank', 32, 26, 'Out of the price measures (R8)'],
]);

const cleaning = table([900, 5466, 2050, 2050], [
  ['Rule', 'What it removes (36 months, all regimes)', 'Rows removed', 'Rows left'],
  ['', 'Rows loaded', '', 11135207],
  ['R1', 'TIN not 10 digits', 1325413, 9809794],
  ['R3', 'Cancelled declarations', 56004, 9753790],
  ['R4', 'Regimes other than IM4 and IM7', 3396602, 6357188],
  ['R13', 'APC 483', 8083, 6349105],
  ['R14', 'Older declaration IDs of the same entry', 0, 6349105],
  ['R15', 'Motor vehicle declarations (headings 8701 to 8708, 8711)', 2284966, 4064139],
  ['R5', 'Repeated copies of an item', 76, 4064063],
]);

const doc = new Document({
  numbering: { config: [{ reference: 'b', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•',
    alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 300, hanging: 200 } } } }] }] },
  sections: [{ properties: { page: { size: { width: 11906, height: 16838 },
    margin: { top: 760, bottom: 600, left: 720, right: 720 } } }, children: [
    para(run('CTRP: data exploration report', { bold: true, size: 30, color: '1F4E79' }), { spacing: { after: 30 } }),
    para([b('To: '), run('Kwera Stella    '), b('From: '), run('Ethan Mugire    '), b('Date: '), run('22 October 2026')]),
    para([b('Data: '), run('vw_cstm_AEO_model, IM4 and IM7, 24 months to 30 September 2026, unless stated. '),
          b('Attached: '), run('one Excel workbook per issue (E01 to E11), listing every declaration and taxpayer.')]),

    head('1. Missing data'),
    bullet([b('Original tax '), run('is blank on 24.8% of rows, rising each year (21.6%, 23.6%, 27.1%). It is blank on '
      + '37.1% of declarations without a top-up but only 0.04% of those with one, so a blank most likely means the tax '
      + 'was not changed. The model then uses the final tax. This is our reading, not stated in the data.')]),
    bullet([b('Lane flags '), run('look half empty (red blank on 48.9% of rows), but the flags build on each other: red '
      + 'declarations also carry yellow and green, yellow ones also green. 97.0% of the 1,301,602 declarations follow '
      + 'this, so a blank means "not this lane". 28,486 (2.2%) carry no flag at all.')]),

    head('2. Duplicates'),
    bullet([b('Entries: '), run('no entry appears under more than one declaration ID (E01). The model still keys each '
      + 'entry by entry number, station and year and keeps the latest ID, so an amended entry is never counted twice.')]),
    bullet([b('Items: '), run('7,783 items appear more than once, up to 412 times, about 20% of all rows (E02), on 7,568 '
      + 'declarations of 154 taxpayers. The item table holds the repeats (header and inspection rows do not), and '
      + '99.6% are on motor vehicle declarations, which the model drops. After that only 76 repeated rows remain.')]),

    head('3. Cleaning'),
    cleaning,

    head('4. The issues, with the evidence in the attached workbooks'),
    issues,
    para(run('E08 and E09 come from a 1 in 50 sample, scaled up. Each workbook has the issue, every declaration (entry '
      + 'number, station, year, ID, taxpayer, tax, flags), the taxpayers, and how to check it in ASYCUDA or the data lake.',
      { italics: true, size: 16 }), { spacing: { before: 30, after: 30 } }),

    head('5. Features'),
    para('The model reads 25 features: 8 for the compliance history scorecard (Track A) and 17 on behaviour (Track B). '
      + 'The notebook builds them step by step from the Hue extract (snapshot 31 March 2026, 35,281 taxpayers) and '
      + 'checks them against the production code: all 64 columns of the final dataset are the same.'),

    head('6. What I need'),
    bullet([b('Your confirmation '), run('that a blank original tax means unchanged (E08), and that a tax rise with no '
      + 'top-up flag is not a top-up (E07).')]),
    bullet([b('Data Engineering '), run('to explain the repeated item rows on vehicle declarations, and the 28,486 '
      + 'declarations with no lane flag.')]),
  ] }],
});

Packer.toBuffer(doc).then(buf => fs.writeFileSync(process.argv[2] || 'CTRP_EDA_note_for_Stella.docx', buf));
