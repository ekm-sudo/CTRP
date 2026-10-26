// One-page, plain-language summary of the CTRP data check for Kwera Stella.
// Run: node docs/build_stella_one_page.js <out.docx>
const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
        BorderStyle, PageOrientation, VerticalAlign } = require('docx');

const FONT = 'Arial';
const run = (t, o = {}) => new TextRun({ text: t, font: FONT, size: 18, ...o });
const para = (parts, o = {}) => new Paragraph({ spacing: { after: 50 }, ...o,
  children: (Array.isArray(parts) ? parts : [parts]).map(p => typeof p === 'string' ? run(p) : p) });
const b = t => run(t, { bold: true });

const border = { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' };
const borders = { top: border, bottom: border, left: border, right: border };
const WIDTHS = [1900, 3150, 2300, 2250, 2700, 3338];          // sums to 15638, the page width less margins
const cell = (text, i, head, fill) => new TableCell({
  width: { size: WIDTHS[i], type: WidthType.DXA }, borders, verticalAlign: VerticalAlign.TOP,
  margins: { top: 30, bottom: 30, left: 70, right: 70 },
  shading: fill ? { type: ShadingType.CLEAR, fill, color: 'auto' } : undefined,
  children: [new Paragraph({ children: [run(text, { bold: head || i === 0, size: 18, color: head ? 'FFFFFF' : undefined })] })] });

const HEAD = ['Issue', 'What we found', 'What we think it means', 'What we did', 'Why', 'Risk if we are wrong'];
const ROWS = [
  ['1. The same item row repeated (E02)',
   '7,783 items appear many times, up to 412 times each, on 7,568 declarations of 154 taxpayers. That is 927,778 '
   + 'extra rows, 1 in every 5 rows. 98% are motorcycles.',
   'A fault in how the item table stores or loads these declarations, not extra goods. The copies are identical, '
   + 'even the date and status.',
   'Kept each item once. Left out all motor vehicle declarations.',
   'Counting the copies makes UGX 23.3 billion of goods look like UGX 2,073 billion (89 times), and UGX 10.1 billion '
   + 'of tax look like UGX 942 billion.',
   'If the copies were real goods, we would undercount them. Unlikely: each item says quantity 1. Vehicles are '
   + 'out of the model anyway.'],
  ['2. Original tax blank (E08)',
   'Blank on 24.8% of rows, rising each year (21.6%, 23.6%, 27.1%). Blank on 37% of declarations with no top-up, '
   + 'but on only 0.04% of those with one.',
   'The tax was never changed, so there was no separate original amount to record.',
   'Used the final tax as the original tax.',
   'If the blank hid a change, it would show up on top-ups too. It almost never does.',
   'Small: only 30 of 79,834 topped-up declarations have a blank, so at most 30 top-ups are missed.'],
  ['3. Lane flags blank',
   'Red flag blank on 49% of rows, yellow on 25%. But red declarations also carry yellow and green, and yellow ones '
   + 'carry green: 97% of 1.3 million declarations fit this.',
   'Blank means "not in this lane", not "missing".',
   'Read a blank as 0 (not checked).',
   'The flags fit together the same way 97% of the time.',
   '28,486 declarations (2.2%) have no flag at all. Lanes are only used to test the model, never to score a taxpayer.'],
  ['4. Tax went up, but no top-up flag (E07)',
   '7,031 declarations of 1,929 taxpayers.',
   'Corrections that customs did not mark as top-ups.',
   'Not counted as top-ups.',
   'The flag is customs\' own decision that a top-up happened.',
   'If they are top-ups, we miss about 1 in 10 top-ups (7,031 on top of about 69,700). Needs your confirmation.'],
  ['5. Top-up flag, but tax did not go up (E06)',
   '10,087 declarations of 4,919 taxpayers: flag Y, final tax not above the original.',
   'The flag was set, but no extra tax was raised.',
   'A top-up counts only if the flag is Y and the tax went up.',
   'A top-up with no extra tax is not a top-up.',
   'If the flag is right and the amounts wrong, we miss 10,087 top-ups (13% of flagged declarations).'],
  ['6. top_up_amt column wrong (E09)',
   'On declarations with no top-up, top_up_amt equals the whole final tax 99.5% of the time: about 628,000 declarations.',
   'The column holds the wrong number.',
   'Ignored it. Top-up = final tax minus original tax.',
   'Using it would make about 628,000 normal declarations look 100% topped up.',
   'None, as long as the original and final tax are right.'],
  ['7. Cancelled declarations (E04)',
   '9,894 declarations of 1,809 taxpayers. The status column says "Cancelled".',
   'The declaration did not go ahead.',
   'Removed them.',
   'No goods cleared, no tax paid: they say nothing about how a taxpayer behaves.',
   'Low: the status comes straight from ASYCUDA.'],
  ['8. APC 483 (E05)',
   '1,582 declarations of 356 taxpayers.',
   'Destroyed or abandoned goods, or dummy entries (CPC memo).',
   'Removed them.',
   'They are not trade.',
   'Low.'],
  ['9. Value or weight missing (E11)',
   '32 declarations of 26 taxpayers.',
   'Keying gaps.',
   'Left out of the price checks only.',
   'A price per kg needs both a value and a weight.',
   'Very small: 32 declarations.'],
  ['10. Same entry under two IDs (E01), bad TINs (E03)',
   'None found.',
   'The data is clean on these.',
   'Kept the rules as a safety net: latest ID per entry, 10-digit TINs only.',
   'So a future problem cannot slip in.',
   'None today.'],
];

const table = new Table({
  width: { size: 15638, type: WidthType.DXA }, columnWidths: WIDTHS,
  rows: [new TableRow({ tableHeader: true, children: HEAD.map((h, i) => cell(h, i, true, '1F4E79')) }),
         ...ROWS.map((r, k) => new TableRow({ children: r.map((t, i) => cell(t, i, false, k % 2 ? 'F2F6FC' : undefined)) }))],
});

const doc = new Document({
  sections: [{ properties: { page: { size: { width: 11906, height: 16838, orientation: PageOrientation.LANDSCAPE },
    margin: { top: 600, bottom: 500, left: 600, right: 600 } } }, children: [
    para(run('CTRP data check: what we found and what we did', { bold: true, size: 30, color: '1F4E79' }),
         { spacing: { after: 30 } }),
    para([b('To: '), run('Kwera Stella    '), b('From: '), run('Ethan Mugire    '), b('Date: '), run('22 October 2026')]),
    para([b('The data: '), run('customs import declarations (IM4 and IM7) for the 24 months to 30 September 2026: '
      + '4.6 million item rows on 1.3 million declarations. Before the model uses them, we checked them for gaps, '
      + 'copies and errors. '), b('The evidence: '), run('for rows 2, 4, 5, 6 and 9, an Excel workbook lists every '
      + 'declaration and taxpayer behind the issue.')], { spacing: { after: 90 } }),
    table,
    para([b('What we need: '), run('your confirmation of rows 2 and 4. From Data Engineering: the cause of row 1, and '
      + 'what the 28,486 declarations with no lane flag are (row 3).')], { spacing: { before: 90 } }),
  ] }],
});

Packer.toBuffer(doc).then(buf => fs.writeFileSync(process.argv[2] || 'CTRP_data_check_one_page.docx', buf));
