/**
 * TiDB Cloud Pitch & Demo Script Generator
 * GTM Playbook Edition — March 2026
 *
 * Generates: TIDB_PITCH_AND_DEMO_SCRIPTS.docx
 * Run: node generate_pitch_doc.js
 */

"use strict";

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
} = require('docx');
const fs = require('fs');

// ── Colour palette ──────────────────────────────────────────────────────────
const RED      = 'DC150B';   // TiDB primary red
const ORANGE   = 'E85D04';   // accent orange
const DARK     = '1A1A2E';
const MUTED    = '6B7280';
const LIGHT_BG = 'FFF3E0';
const RED_BG   = 'FEF2F2';
const RED_LINE = 'DC2626';
const GREEN_BG = 'F0FDF4';
const GREEN_LINE = '16A34A';
const WHITE    = 'FFFFFF';
const GREY_BG  = 'F9FAFB';

// ── Page geometry (US Letter, 1" margins) ───────────────────────────────────
const PAGE_W    = 12240;
const PAGE_H    = 15840;
const MARGIN    = 1440;
const CONTENT_W = PAGE_W - 2 * MARGIN;  // 9360 DXA

// ── Typography helpers ────────────────────────────────────────────────────────

function heading1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 400, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: RED, space: 6 } },
    children: [new TextRun({ text, font: 'Arial', size: 34, bold: true, color: DARK })],
  });
}

function heading2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 300, after: 80 },
    children: [new TextRun({ text, font: 'Arial', size: 26, bold: true, color: DARK })],
  });
}

function heading3(text) {
  return new Paragraph({
    spacing: { before: 220, after: 60 },
    children: [new TextRun({ text, font: 'Arial', size: 22, bold: true, color: RED })],
  });
}

function label(text) {
  return new Paragraph({
    spacing: { before: 160, after: 40 },
    children: [new TextRun({ text: text.toUpperCase(), font: 'Arial', size: 18, bold: true, color: MUTED, characterSpacing: 40 })],
  });
}

function body(text, opts = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 100 },
    children: [new TextRun({
      text,
      font: 'Arial',
      size: 22,
      color: opts.muted ? MUTED : DARK,
      italics: opts.italic || false,
      bold: opts.bold || false,
    })],
  });
}

function speech(text) {
  return new Paragraph({
    spacing: { before: 100, after: 100 },
    indent: { left: 480 },
    children: [
      new TextRun({ text: '\u201C', font: 'Arial', size: 22, color: RED, bold: true }),
      new TextRun({ text, font: 'Arial', size: 22, color: DARK, italics: true }),
      new TextRun({ text: '\u201D', font: 'Arial', size: 22, color: RED, bold: true }),
    ],
  });
}

function bullet(text, opts = {}) {
  return new Paragraph({
    numbering: { reference: 'bullets', level: 0 },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, font: 'Arial', size: 22, color: opts.color || DARK, bold: opts.bold || false })],
  });
}

function spacer(n = 1) {
  return Array.from({ length: n }, () =>
    new Paragraph({ spacing: { before: 0, after: 0 }, children: [new TextRun('')] })
  );
}

// ── Callout boxes ─────────────────────────────────────────────────────────────

function callout(label, text, opts = {}) {
  const color  = opts.color  || RED;
  const fill   = opts.fill   || 'FEF2F2';
  const border = { style: BorderStyle.SINGLE, size: 2, color };
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    rows: [new TableRow({
      children: [new TableCell({
        borders: { top: { style: BorderStyle.THICK, size: 12, color }, bottom: border, left: { style: BorderStyle.THICK, size: 12, color }, right: border },
        shading: { fill, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 200, right: 180 },
        width: { size: CONTENT_W, type: WidthType.DXA },
        children: [
          new Paragraph({
            spacing: { before: 0, after: 60 },
            children: [new TextRun({ text: label, font: 'Arial', size: 18, bold: true, color, characterSpacing: 40 })],
          }),
          new Paragraph({
            spacing: { before: 0, after: 0 },
            children: [new TextRun({ text, font: 'Arial', size: 22, color: DARK })],
          }),
        ],
      })],
    })],
  });
}

function greenCallout(label, text) {
  return callout(label, text, { color: GREEN_LINE, fill: GREEN_BG });
}

function codeBlock(lines) {
  const border = { style: BorderStyle.SINGLE, size: 1, color: '374151' };
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    rows: [new TableRow({
      children: [new TableCell({
        borders: { top: border, bottom: border, left: border, right: border },
        shading: { fill: '1F2937', type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 200, right: 200 },
        width: { size: CONTENT_W, type: WidthType.DXA },
        children: lines.map(line => new Paragraph({
          spacing: { before: 0, after: 20 },
          children: [new TextRun({ text: line, font: 'Courier New', size: 18, color: '86EFAC' })],
        })),
      })],
    })],
  });
}

// ── Tables ────────────────────────────────────────────────────────────────────

function proofTable(rows) {
  const col1 = 2200, col2 = 3580, col3 = 3580;
  const hBorder = { style: BorderStyle.SINGLE, size: 1, color: RED };
  const cBorder = { style: BorderStyle.SINGLE, size: 1, color: 'E5E7EB' };
  const widths  = [col1, col2, col3];

  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ children: ['Pain Point', 'Fragmented Stack (Before)', 'TiDB Cloud (After)'].map((h, i) =>
        new TableCell({
          borders: { top: hBorder, bottom: hBorder, left: hBorder, right: hBorder },
          shading: { fill: RED, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          width: { size: widths[i], type: WidthType.DXA },
          children: [new Paragraph({ children: [new TextRun({ text: h, font: 'Arial', size: 20, bold: true, color: WHITE })] })],
        })
      )}),
      ...rows.map(([pain, without, with_], idx) =>
        new TableRow({ children: [pain, without, with_].map((cell, i) =>
          new TableCell({
            borders: { top: cBorder, bottom: cBorder, left: cBorder, right: cBorder },
            shading: { fill: idx % 2 === 0 ? 'FFFFFF' : GREY_BG, type: ShadingType.CLEAR },
            margins: { top: 80, bottom: 80, left: 120, right: 120 },
            width: { size: widths[i], type: WidthType.DXA },
            children: [new Paragraph({ children: [new TextRun({ text: cell, font: 'Arial', size: 20, color: DARK })] })],
          })
        )})
      ),
    ],
  });
}

function vsTable(headers, rows, headerColor) {
  const colW = Math.floor(CONTENT_W / headers.length);
  const remainder = CONTENT_W - colW * headers.length;
  const widths = headers.map((_, i) => i === headers.length - 1 ? colW + remainder : colW);
  const hBorder = { style: BorderStyle.SINGLE, size: 1, color: headerColor || DARK };
  const cBorder = { style: BorderStyle.SINGLE, size: 1, color: 'E5E7EB' };

  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ children: headers.map((h, i) =>
        new TableCell({
          borders: { top: hBorder, bottom: hBorder, left: hBorder, right: hBorder },
          shading: { fill: headerColor || DARK, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          width: { size: widths[i], type: WidthType.DXA },
          children: [new Paragraph({ children: [new TextRun({ text: h, font: 'Arial', size: 20, bold: true, color: WHITE })] })],
        })
      )}),
      ...rows.map((cells, idx) =>
        new TableRow({ children: cells.map((cell, i) => {
          const isLast = i === cells.length - 1;
          const fill   = isLast ? GREEN_BG : (i === 1 && cells.length === 3 ? RED_BG : 'FFFFFF');
          return new TableCell({
            borders: { top: cBorder, bottom: cBorder, left: cBorder, right: cBorder },
            shading: { fill, type: ShadingType.CLEAR },
            margins: { top: 80, bottom: 80, left: 120, right: 120 },
            width: { size: widths[i], type: WidthType.DXA },
            children: [new Paragraph({ children: [new TextRun({ text: cell, font: 'Arial', size: 19, color: DARK })] })],
          });
        })})
      ),
    ],
  });
}

function personaTable(rows) {
  const col1 = 2400, col2 = 6960;
  const hBorder = { style: BorderStyle.SINGLE, size: 1, color: DARK };
  const cBorder = { style: BorderStyle.SINGLE, size: 1, color: 'E5E7EB' };

  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [col1, col2],
    rows: [
      new TableRow({ children: ['Persona', 'Opening Line'].map((h, i) =>
        new TableCell({
          borders: { top: hBorder, bottom: hBorder, left: hBorder, right: hBorder },
          shading: { fill: DARK, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          width: { size: [col1, col2][i], type: WidthType.DXA },
          children: [new Paragraph({ children: [new TextRun({ text: h, font: 'Arial', size: 20, bold: true, color: WHITE })] })],
        })
      )}),
      ...rows.map(([persona, line], idx) =>
        new TableRow({ children: [
          new TableCell({
            borders: { top: cBorder, bottom: cBorder, left: cBorder, right: cBorder },
            shading: { fill: idx % 2 === 0 ? 'FFFFFF' : GREY_BG, type: ShadingType.CLEAR },
            margins: { top: 80, bottom: 80, left: 120, right: 120 },
            width: { size: col1, type: WidthType.DXA },
            children: [new Paragraph({ children: [new TextRun({ text: persona, font: 'Arial', size: 20, bold: true, color: RED })] })],
          }),
          new TableCell({
            borders: { top: cBorder, bottom: cBorder, left: cBorder, right: cBorder },
            shading: { fill: idx % 2 === 0 ? 'FFFFFF' : GREY_BG, type: ShadingType.CLEAR },
            margins: { top: 80, bottom: 80, left: 120, right: 120 },
            width: { size: col2, type: WidthType.DXA },
            children: [new Paragraph({ children: [new TextRun({ text: `\u201C${line}\u201D`, font: 'Arial', size: 20, italics: true, color: DARK })] })],
          }),
        ]})
      ),
    ],
  });
}

// ── Document sections ─────────────────────────────────────────────────────────

function coverSection() {
  return [
    ...spacer(3),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 40 },
      children: [new TextRun({ text: 'TiDB Cloud', font: 'Arial', size: 80, bold: true, color: RED })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 80 },
      children: [new TextRun({ text: 'Pitch & Demo Scripts', font: 'Arial', size: 48, bold: true, color: DARK })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 80 },
      children: [new TextRun({ text: 'The Database for the Agent Era', font: 'Arial', size: 30, italics: true, color: MUTED })],
    }),
    new Paragraph({
      spacing: { before: 200, after: 200 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RED, space: 1 } },
      children: [new TextRun('')],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 120, after: 40 },
      children: [new TextRun({ text: 'GTM Playbook Edition  \u2014  March 2026', font: 'Arial', size: 20, color: MUTED })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 60 },
      children: [new TextRun({ text: 'CONFIDENTIAL  |  PingCAP', font: 'Arial', size: 20, color: MUTED })],
    }),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function strategicContextSection() {
  return [
    heading1('SECTION 1 \u2014 The Strategic Context: Why Now'),
    callout(
      'CEO FRAMING \u2014 MAX LIU, PINGCAP',
      '\u201CThe primary users of databases are becoming AI agents. Not in five years. Now.\u201D',
      { color: RED, fill: RED_BG }
    ),
    ...spacer(1),
    body(
      'Before you pitch TiDB Cloud, internalise this: we are not adding AI features to a database. ' +
      'We are the first database purpose-built for the era where AI agents are the primary users. ' +
      'This is not a product update. It is an identity declaration.',
    ),
    ...spacer(1),

    heading2('The 36-Month Window'),
    body(
      'The category \u2014 \u201Cthe database for AI agents\u201D \u2014 is unclaimed. Starting March 2026, ' +
      'there is a 36-month window. After that, the market will consolidate. Speed is not an execution detail. Speed is strategy.'
    ),
    ...spacer(1),

    heading2('Three Moments That Changed Everything'),
    bullet(
      'An AI agent debugged a production issue overnight \u2014 queried the DB, correlated logs, identified root cause, ' +
      'patched code, and deployed. No human in the loop. The database was no longer queried by a human mind.'
    ),
    bullet(
      'Over 95% of new TiDB Cloud clusters are now created by AI agents, not human developers. ' +
      'Automated pipelines, LLM-powered coding agents, and orchestration frameworks are the new majority users.'
    ),
    bullet(
      'An AI-native founder described requirements that broke the old model. He didn\u2019t think in tables and indexes. ' +
      'He thought in tasks, memory, tool access, and context windows. His agents needed many databases \u2014 for state, ' +
      'for memory, for context, for coordination.'
    ),
    ...spacer(1),

    heading2('The Identity Shift'),
    body('Use this framing in every call:', { bold: true }),
    callout(
      'THE CORE NARRATIVE',
      'The database was the system of record. In the agent era, it becomes the system of thought. ' +
      'Seat-based pricing assumed human users. When users are agents, the entire value chain restructures. ' +
      'AI-enabled is incremental. Agent-native is foundational. Bolt-ons will fail.',
      { color: RED, fill: RED_BG }
    ),
    ...spacer(2),
  ];
}

function elevatorSection() {
  return [
    heading1('SECTION 2 \u2014 Elevator Pitches'),
    body('Use the right pitch for the right moment. All versions share the same DNA \u2014 the Memory Wall, the Unified Foundation, and the Agent-Native value.', { muted: true, italic: true }),
    ...spacer(1),

    heading2('The 30-Second Pitch  (Cold Intro / Networking)'),
    speech(
      'Most AI agents today are hitting a Memory Wall. They stitch together a SQL database, a vector store, ' +
      'and object storage just to give an agent coherent memory \u2014 and that fragmentation kills velocity and balloons cost. ' +
      'TiDB Cloud is the first database built from the ground up for agents: unified transactional memory, vector context, ' +
      'and real-time analytics in a single ACID-compliant engine. One system. No ETL. Pay only when your agents are thinking.'
    ),
    ...spacer(1),

    heading2('The 60-Second Pitch  (Qualified Meeting / First Call)'),
    label('The Hook \u2014 Earn their attention'),
    speech(
      'Your engineers are paying an \u201cAgentic Tax.\u201d They\u2019re spending 70% of sprint cycles as data plumbers \u2014 ' +
      'stitching together Postgres, Pinecone, and S3 just to give their AI agents coherent memory. Every time data crosses ' +
      'a system boundary, you pay in latency, engineering overhead, and hallucination risk. ' +
      'This is the Memory Wall, and it is costing you your GTM window.'
    ),
    ...spacer(1),
    label('The Solution \u2014 Land the value'),
    speech(
      'TiDB Cloud is the Unified Agentic Data Foundation. A single ACID-compliant engine where transactional memory, ' +
      'vector context, and real-time analytics live together. With Serverless Branching \u2014 think Git for your database \u2014 ' +
      'your agents can fork an entire production environment in milliseconds, test hypotheses in a safe sandbox, and promote ' +
      'changes with zero downtime. No ETL. No data lag. No production anxiety.'
    ),
    ...spacer(1),
    label('The Value \u2014 Close for the next step'),
    speech(
      'We eliminate 80% of your data plumbing, reduce TCO by up to 80% through pay-per-second scaling, and give your agents ' +
      'a safety-first playground to evolve. Our partner Manus runs over 10 million ephemeral databases on TiDB Cloud today. ' +
      'That is the scale agents demand \u2014 and it is what we are built for. Can I show you a 5-minute demo?'
    ),
    ...spacer(1),

    heading2('Persona-Specific Opening Lines'),
    body('Tailor your hook before launching into the core pitch:', { muted: true, italic: true }),
    ...spacer(1),
    personaTable([
      [
        'CTO / VP Engineering',
        'Most CTOs I talk to have a dirty secret: their AI agents are only as smart as their worst data pipeline. How much of your sprint is your team spending on data plumbing vs. building agent logic?',
      ],
      [
        'Head of Data & AI',
        'If your agents are reasoning on yesterday\u2019s data because of ETL lag, they\u2019re already behind your competitors. What would it mean to give them zero-lag context across every data type in a single query?',
      ],
      [
        'AI/ML Platform Lead',
        'We just launched a native MCP Server for TiDB. Your agents can interact with your entire data substrate in natural language \u2014 no middleware, no custom connectors. Want to see it?',
      ],
      [
        'VP Product',
        'Every product leader I talk to is fighting two fires: AI hallucinations and skyrocketing infra costs. What if I told you both problems have the same root cause \u2014 and the same fix?',
      ],
      [
        'CCO / Chief Risk Officer',
        'What does your compliance team do when an AI agent touches production data? With TiDB, every autonomous action lands in a single auditable transaction log. GDPR right to be forgotten becomes one SQL command.',
      ],
    ]),
    ...spacer(2),
  ];
}

function fullDemoSection() {
  return [
    heading1('SECTION 3 \u2014 Full Demo Setup Guide  (5 minutes)'),
    body('This is your weapon in the room. A well-run demo closes deals. Follow this guide precisely \u2014 every scene, every visual, every line is engineered for maximum impact.', { muted: true, italic: true }),
    ...spacer(1),

    heading2('Pre-Demo Checklist'),
    bullet('TiDB Cloud console open, logged in, cluster running in the correct region'),
    bullet('TiFlash (columnar) and Vector Search enabled on the demo table'),
    bullet('agent_memory table pre-populated with sample SQL logs and vector embeddings'),
    bullet('DBA Agent UI open in second tab \u2014 slow query pre-loaded (full table scan, 2M rows)'),
    bullet('Branch already named but not yet created \u2014 visible in the UI'),
    bullet('Performance comparison data ready: Production 2.1s vs. Branch 3ms (700x improvement)'),
    bullet('Screen resolution set to 1280\u00D7800 minimum for screen share clarity'),
    bullet('Notifications silenced. Slack closed. Browser in full screen.'),
    bullet('Run through the full demo end-to-end within 24 hours of the meeting'),
    callout(
      'BACKUP PLAN',
      'Record a backup video of the perfect run. If live connectivity fails, you have a fallback that still tells the full story.',
      { color: ORANGE, fill: LIGHT_BG }
    ),
    ...spacer(1),

    // Scene 1
    heading2('Scene 1: The Unified Foundation  (0:00 \u2013 1:00)'),
    label('Goal'),
    body('Destroy the assumption that you need multiple systems.'),
    label('Visual'),
    body('TiDB Cloud Console \u2014 single table with TiFlash (Columnar) and Vector Search toggled on simultaneously.'),
    ...spacer(1),
    callout(
      'OPENING STAT \u2014 DROP THIS FIRST',
      '95% of new TiDB Cloud clusters are now created by AI agents, not human developers. ' +
      'Our partner Manus manages over 10 million databases on TiDB today. ' +
      'We didn\u2019t add AI features to a database. We built the database that AI agents actually need.',
      { color: RED, fill: RED_BG }
    ),
    ...spacer(1),
    speech(
      'This is where we start. One table. I\u2019m going to show you something you can\u2019t do in any other database today.'
    ),
    body('[Toggle TiFlash on. Toggle Vector Search on.]', { muted: true, italic: true }),
    speech(
      'Whether our agent needs a vector embedding for long-term memory, or a columnar scan for complex analytics \u2014 ' +
      'it all happens here. Real-time. Zero ETL. Zero lag. The agent sees the world exactly as it is right now \u2014 ' +
      'not as it was when the last batch job ran.'
    ),
    callout(
      'SELLING POINT TO LAND',
      'Most of your competitors\u2019 AI stacks have a clock problem. Every ETL pipeline introduces lag \u2014 and agents ' +
      'reasoning on stale data hallucinate or make bad decisions. We eliminate that clock entirely. ' +
      'This is what it means for your database to become the system of thought.',
      { color: ORANGE, fill: LIGHT_BG }
    ),
    ...spacer(1),

    // Scene 1b (optional)
    heading2('Scene 1b: MCP Server \u2014 Natural Language to SQL  (Optional \u2014 AI/ML Persona)'),
    label('Goal'),
    body('Show the native MCP Server for AI/ML Platform Leads \u2014 most compelling 30 seconds in the entire demo for this persona.'),
    label('Visual'),
    body('Chat2Query / MCP interface \u2014 agent querying the database in natural language.'),
    ...spacer(1),
    speech(
      'Our native MCP Server means your agents interact with the entire data substrate in natural language \u2014 ' +
      'no middleware, no custom connectors. Watch this: I type a question in plain English, and TiDB translates it ' +
      'into optimised SQL and vector search automatically. This is how your Claude or LangChain agents talk to your database.'
    ),
    ...spacer(1),

    // Scene 2
    heading2('Scene 2: The Programmable Branch  (1:00 \u2013 2:30)'),
    label('Goal'),
    body('Make the Safety-First story visceral and concrete.'),
    label('Visual'),
    body('DBA Agent UI \u2014 agent has flagged a slow query (full table scan on 2M rows).'),
    ...spacer(1),
    speech(
      'The agent just found a performance bottleneck. In a legacy stack, an agent running CREATE INDEX on production ' +
      'is a firing offense. You\u2019re one bad command away from a P1 incident.'
    ),
    body('[Click to fork \u2014 show the branch creation happening in under a second.]', { muted: true, italic: true }),
    speech(
      'But TiDB is a programmable substrate. The agent forks the entire database \u2014 copy-on-write, milliseconds, ' +
      'nearly free. This branch is the ultimate sandbox: safe, isolated, and invisible to your live users. ' +
      'The agent can be wrong in here. That\u2019s the point.'
    ),
    callout(
      'OBJECTION HANDLER',
      '\u201CBut we already have a staging environment.\u201D Response: A staging environment is one. ' +
      'TiDB lets every agent \u2014 every experiment \u2014 have its own. You can run thousands of hypotheses in parallel. ' +
      'That\u2019s not staging. That\u2019s machine-speed R&D.',
      { color: ORANGE, fill: LIGHT_BG }
    ),
    ...spacer(1),

    // Scene 3
    heading2('Scene 3: Validation & Online DDL  (2:30 \u2013 4:00)'),
    label('Goal'),
    body('Show the proof, then the promotion \u2014 zero drama.'),
    label('Visual'),
    body('Side-by-side comparison report. Production branch: 2.1 seconds. Agent branch: 3 milliseconds.'),
    ...spacer(1),
    speech(
      'The agent applied the index in the branch. Here is the proof: 700x performance improvement. ' +
      'It doesn\u2019t guess. It validates. Now watch this \u2014 human-in-the-loop.'
    ),
    body('[Click \u2018Approve\u2019.]', { muted: true, italic: true }),
    speech(
      'We use Online DDL to promote the change to the live cluster. No downtime. No row-locking. ' +
      'No maintenance window. The index is applied while your application keeps running.'
    ),
    callout(
      'COMPLIANCE HOOK \u2014 FOR EU AI ACT PERSONAS',
      'Every step of this process \u2014 the fork, the test, the approval, the promotion \u2014 is captured in a single ' +
      'auditable transaction log. That is your EU AI Act Article 14 compliance, built into the workflow.',
      { color: RED, fill: RED_BG }
    ),
    ...spacer(1),

    // Scene 4
    heading2('Scene 4: Episodic Memory \u2014 The System Learns  (4:00 \u2013 5:00)'),
    label('Goal'),
    body('Shift the frame from \u201Cdatabase\u201D to \u201Clearning system.\u201D This is the scene no competitor can show.'),
    label('Visual'),
    body('agent_memory table \u2014 SQL logs stored alongside vector embeddings. Show both structured data and vector columns in one table.'),
    ...spacer(1),
    speech(
      'Finally, the agent writes this experience back to TiDB as Episodic Memory. The problem, the fix, and the result \u2014 ' +
      'stored as a vector embedding. Next time a similar bottleneck appears anywhere in your fleet, the agent recalls this event ' +
      'and resolves it instantly. No re-learning. No repeated mistakes.'
    ),
    body('[Pause. Let it land.]', { muted: true, italic: true }),
    speech(
      'We\u2019ve moved from a static database to a learning system. This is what it means for the database to become ' +
      'the system of thought \u2014 not just storing what happened, but remembering what worked.'
    ),
    callout(
      'CLOSE STRONG',
      'What you\u2019ve just seen is the Decide-Validate-Remember loop. Most databases can only do the first. ' +
      'TiDB closes the loop. That is the difference between an AI tool and an AI colleague.',
      { color: RED, fill: RED_BG }
    ),
    ...spacer(1),

    // Post-demo
    heading2('Post-Demo: Three Conversation Starters'),
    body('After the demo, use one of these to pivot to discovery:', { muted: true, italic: true }),
    ...spacer(1),
    label('The Cost Question'),
    speech(
      'Right now, how much of your infra spend is on databases your agents are barely using \u2014 because you have to ' +
      'overprovision for spiky workloads? We can model your potential TCO reduction in 15 minutes.'
    ),
    label('The Speed Question'),
    speech(
      'If your engineering team had 70% of their time back from data plumbing \u2014 what would they build first? ' +
      'That\u2019s what TiDB gives back.'
    ),
    label('The Compliance Question'),
    speech(
      'Who in your organisation needs to sign off on AI agents touching production data? ' +
      'Because what I\u2019ve just shown you is how you get them to say yes.'
    ),
    ...spacer(2),
  ];
}

function proofPointsSection() {
  return [
    heading1('SECTION 4 \u2014 Key Technical Proof Points  (Q&A / Slides)'),
    ...spacer(1),
    proofTable([
      [
        'Memory Wall',
        'Siloed: SQL + Vector + S3 \u2014 70% of eng time on glue code; hallucinations from stale context',
        'Unified HTAP substrate with native vector search \u2014 80% less glue code; system of thought, not storage',
      ],
      [
        'Stale Context',
        'ETL lag: analytics run on yesterday\u2019s data; vector store out of sync with transactions',
        'Zero-ETL HTAP: reads live operational data \u2014 instant churn risk, real-time sentiment, no clock problem',
      ],
      [
        'Episodic Memory',
        'Agent decisions lost after each session; no structured + vector unified store; no Decide-Validate-Remember loop',
        'Agents write experience back as vector embeddings in the same ACID engine \u2014 system learns over time',
      ],
      [
        'Prod Safety',
        'No safe sandbox; agents touching production = P1 risk; no human-in-the-loop guardrails',
        'Serverless Branching: copy-on-write snapshot in seconds; 700x improvement proven in isolation before merge',
      ],
      [
        'Compliance',
        'Multi-system audit trail spanning Postgres + vector DB + S3; GDPR cleanup is a multi-team project',
        'Single ACID transaction log; Right to be Forgotten = one SQL command; Online DDL; EU AI Act Article 14 ready',
      ],
      [
        'TCO',
        'Always-on provisioned capacity: paying 24/7 for idle instances across 3+ vendors',
        'Pay-per-second serverless; 80% TCO reduction; Manus manages 10M+ databases on TiDB Cloud today',
      ],
      [
        'MCP / Agent Integration',
        'Custom connectors, middleware layers, and bespoke adapters for each agent framework',
        'Native MCP Server: agents query full data substrate in natural language \u2014 zero middleware, immediate fit',
      ],
    ]),
    ...spacer(2),
  ];
}

function competitiveSection() {
  return [
    heading1('SECTION 5 \u2014 Competitive Battlecard'),
    body('Prospects will ask about these. Know the answers cold.', { muted: true, italic: true }),
    ...spacer(1),

    heading2('vs. Pinecone / Weaviate / Qdrant  (Pure Vector Databases)'),
    callout(
      'THE ONE-LINER',
      'A vector database is a single-purpose tool. TiDB is the substrate. When your agent needs to correlate a ' +
      'vector result with relational state \u2014 user history, account data, audit logs \u2014 you pay a network round-trip ' +
      'and write glue code. With TiDB, it\u2019s one SQL query. One bill. Zero ETL.',
      { color: DARK, fill: GREY_BG }
    ),
    ...spacer(1),
    vsTable(
      ['Capability', 'Pinecone / Pure Vector DB', 'TiDB Cloud'],
      [
        ['Relational + Vector join', 'Impossible in one query \u2014 app-level join required', 'Native: VEC_COSINE_DISTANCE in same SQL as transactional joins'],
        ['ACID consistency', 'No transactions; vectors can lag relational state', 'Full ACID \u2014 vectors update atomically with relational data'],
        ['Analytics', 'None \u2014 requires a third system (Snowflake/BigQuery)', 'TiFlash columnar built-in \u2014 OLAP + OLTP + Vector in one cluster'],
        ['Episodic Memory', 'Vectors only \u2014 no structured state, no unified Decide-Validate-Remember', 'Unified structured + vector store \u2014 full episodic loop in one engine'],
        ['Audit / Compliance', 'No transaction log; no GDPR tooling', 'Full ACID log; Right to be Forgotten = one SQL command'],
      ]
    ),
    ...spacer(1),

    heading2('vs. Aurora / MySQL  (Database Displacement)'),
    callout(
      'THE ONE-LINER',
      'TiDB is MySQL-compatible at the wire level. Zero application rewrite. But Aurora stops at relational \u2014 ' +
      'your team will bolt on Pinecone or OpenSearch the moment they add vector search. That\u2019s the Memory Wall. ' +
      'TiDB eliminates the second system before you need it.',
      { color: DARK, fill: GREY_BG }
    ),
    ...spacer(1),
    vsTable(
      ['Capability', 'Aurora / MySQL', 'TiDB Cloud'],
      [
        ['Vector Search', 'Not native \u2014 requires pgvector sidecar or OpenSearch', 'Native HNSW; sub-10ms p99; same query plan as relational'],
        ['Analytics (HTAP)', 'Separate read replicas or export to Redshift/BigQuery', 'TiFlash columnar built-in \u2014 live OLAP on operational data'],
        ['Horizontal Scale', 'Manual sharding (Vitess/ProxySQL) or expensive instances', 'Auto-sharding; MySQL-compatible wire protocol; cloud-agnostic'],
        ['Agent Safety', 'No branching; schema changes require maintenance windows', 'Serverless Branching; Online DDL; agent-safe by design'],
        ['Migration Cost', '\u2014', 'Zero application rewrite; existing ORMs and drivers work unchanged'],
      ]
    ),
    ...spacer(1),

    heading2('vs. DynamoDB / Spanner  (NoSQL Displacement)'),
    callout(
      'THE ONE-LINER',
      'DynamoDB and Spanner were built before the agent era. NoSQL constraints mean your agents can\u2019t do relational ' +
      'joins, can\u2019t query vector context, and can\u2019t run analytics \u2014 all in one place. ' +
      'Spanner locks you into GCP proprietary APIs. TiDB is MySQL-compatible and cloud-agnostic.',
      { color: DARK, fill: GREY_BG }
    ),
    ...spacer(1),

    heading2('vs. Snowflake / BigQuery  (Analytics Warehouse)'),
    callout(
      'THE ONE-LINER',
      'Snowflake and BigQuery are read-heavy analytical systems with latency measured in seconds. ' +
      'AI agents need sub-millisecond reads and transactional writes. They need to update state as they reason, ' +
      'not query yesterday\u2019s snapshot. TiDB is HTAP \u2014 OLTP and OLAP in one live system.',
      { color: DARK, fill: GREY_BG }
    ),
    ...spacer(2),
  ];
}

function demoSetupSection() {
  return [
    heading1('SECTION 6 \u2014 Demo SQL Checklist'),
    ...spacer(1),
    body('Run these in the TiDB Cloud SQL Editor during or after the demo:', { bold: true }),
    ...spacer(1),

    body('Data at scale:', { bold: true }),
    codeBlock([
      'SELECT table_name, table_rows,',
      '       ROUND(data_length/1024/1024, 2) AS data_mb',
      'FROM information_schema.tables',
      "WHERE table_schema = 'tidb_leads'",
      "  AND table_type   = 'BASE TABLE'",
      'ORDER BY table_rows DESC;',
    ]),
    ...spacer(1),

    body('Hot leads \u2014 the agent\u2019s episodic intelligence at work:', { bold: true }),
    codeBlock([
      'SELECT company_name, country, fit_score, industry,',
      '       LEFT(tidb_pain, 120)     AS pain_summary,',
      '       LEFT(tidb_use_case, 120) AS use_case,',
      '       status',
      'FROM leads',
      'WHERE fit_score >= 8',
      'ORDER BY fit_score DESC, company_name',
      'LIMIT 20;',
    ]),
    ...spacer(1),

    body('Hybrid semantic search (vector + keyword \u2014 TiDB powering itself as the demo):', { bold: true }),
    codeBlock([
      '-- Find leads matching "AI agent episodic memory" via native vector + keyword hybrid',
      'SELECT company_name, country, fit_score,',
      '       ROUND((1 - VEC_COSINE_DISTANCE(embedding, @query_vec)) * 100, 1) AS similarity_pct,',
      '       LEFT(tidb_use_case, 100) AS use_case',
      'FROM leads',
      'WHERE fit_score >= 6',
      '  AND embedding IS NOT NULL',
      'ORDER BY',
      '  (1 - VEC_COSINE_DISTANCE(embedding, @query_vec)) * 0.7',
      '  + (CASE WHEN tidb_pain LIKE \'%episodic%\' OR tidb_pain LIKE \'%memory%\' THEN 0.3 ELSE 0 END) DESC',
      'LIMIT 10;',
    ]),
    ...spacer(1),

    body('Episodic memory table (Scene 4 \u2014 the learning system):', { bold: true }),
    codeBlock([
      '-- Show agent experiences stored as structured + vector data in one table',
      'CREATE TABLE IF NOT EXISTS agent_memory (',
      '  id          INT AUTO_INCREMENT PRIMARY KEY,',
      '  event_type  VARCHAR(50),       -- slow_query | schema_change | incident',
      '  context_sql TEXT,              -- the SQL that triggered the event',
      '  resolution  TEXT,              -- what the agent did',
      '  outcome_ms  INT,               -- performance before/after',
      '  embedding   VECTOR(384),       -- semantic embedding of the full experience',
      '  created_at  DATETIME DEFAULT NOW()',
      ');',
    ]),
    ...spacer(1),

    body('Regional breakdown:', { bold: true }),
    codeBlock([
      'SELECT region, country,',
      '       COUNT(*) AS leads,',
      '       SUM(CASE WHEN fit_score >= 8 THEN 1 ELSE 0 END) AS hot,',
      '       ROUND(AVG(fit_score), 1) AS avg_score',
      'FROM leads',
      'GROUP BY region, country',
      'ORDER BY avg_score DESC;',
    ]),
    ...spacer(2),
  ];
}

function qnaSection() {
  return [
    heading1('SECTION 7 \u2014 Common Objections & Responses'),
    ...spacer(1),

    heading3('Q: We\u2019re already on Postgres/MySQL. What\u2019s the migration cost?'),
    speech(
      'TiDB Cloud is MySQL-compatible at the wire protocol level \u2014 your existing queries, ORMs, and drivers work ' +
      'without changes. Migration is a logical data move, not an application rewrite. For most teams it\u2019s a weekend ' +
      'project, not a quarter-long initiative. And you keep every index, every stored procedure, every connection string.'
    ),
    ...spacer(1),

    heading3('Q: We already use Pinecone / Weaviate for vectors.'),
    speech(
      'That\u2019s exactly the problem we solve. Every time your agent needs to correlate a vector result with relational ' +
      'data, you pay a network round-trip and write glue code. With TiDB, vector search and SQL joins run in the same query ' +
      'plan \u2014 eliminating the round-trip and the ETL entirely. One fewer service to maintain, one fewer bill to pay. ' +
      'And your vectors stay transactionally consistent with your relational data.'
    ),
    ...spacer(1),

    heading3('Q: How is branching different from staging environments?'),
    speech(
      'A staging environment is one. TiDB lets every agent \u2014 every experiment \u2014 have its own. ' +
      'A TiDB branch is a copy-on-write snapshot: spins up in seconds, stores only the delta, costs nothing when idle. ' +
      'Your DBA agent can create 50 experimental branches per day for the cost of one read-replica hour. ' +
      'That\u2019s not staging. That\u2019s machine-speed R&D.'
    ),
    ...spacer(1),

    heading3('Q: What\u2019s the EU AI Act angle specifically?'),
    speech(
      'Every agent action in TiDB is atomic, durable, and logged in a single auditable transaction log \u2014 ' +
      'which is exactly what Article 14 (human oversight) and Article 12 (logging and documentation) require. ' +
      'Serverless Branching is a built-in human-in-the-loop gate: agents propose, humans approve, changes promote. ' +
      'Right to be Forgotten becomes a single DELETE command that propagates across structured and vector data simultaneously. ' +
      'No multi-system cleanup project. No compliance gap.'
    ),
    ...spacer(1),

    heading3('Q: What is Episodic Memory and why does it matter?'),
    speech(
      'Episodic Memory is how agents learn over time. Instead of treating each session as isolated, the agent writes its ' +
      'experience \u2014 what it did, what the result was, what worked \u2014 back to TiDB as a vector embedding alongside ' +
      'structured data. Next time a similar situation arises, the agent recalls the relevant experience via semantic search ' +
      'and acts on proven knowledge instead of starting from scratch. ' +
      'TiDB is the only database that can store the structured state and the vector memory in the same ACID engine. ' +
      'That\u2019s the Decide-Validate-Remember loop. That\u2019s the difference between an AI tool and an AI colleague.'
    ),
    ...spacer(1),

    heading3('Q: What\u2019s the latency for vector search at scale?'),
    speech(
      'TiDB\u2019s native HNSW vector index delivers sub-10ms p99 semantic search on tens of millions of vectors \u2014 ' +
      'measured inside the same cluster handling your OLTP traffic. No network hop to an external vector DB. And because ' +
      'it shares the same transaction log, your vectors are always consistent with your relational data.'
    ),
    ...spacer(1),

    heading3('Q: How do you handle GDPR / HIPAA compliance at scale?'),
    speech(
      'Every agent action is atomic, durable, and logged in one place. Right to be Forgotten is a single DELETE with a ' +
      'transaction log entry \u2014 not a multi-system cleanup project across Postgres, Pinecone, and S3. ' +
      'Online DDL means schema changes never take your app offline. Audit trails are native \u2014 not bolted on. ' +
      'This is what makes TiDB safe enough for your Chief Risk Officer to sign off on autonomous agents in production.'
    ),
    ...spacer(2),
  ];
}

// ── Build & write ─────────────────────────────────────────────────────────────

async function build() {
  const doc = new Document({
    numbering: {
      config: [{
        reference: 'bullets',
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: '\u2022',
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      }],
    },
    styles: {
      default: { document: { run: { font: 'Arial', size: 22 } } },
      paragraphStyles: [
        {
          id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
          run: { size: 34, bold: true, font: 'Arial', color: DARK },
          paragraph: { spacing: { before: 400, after: 120 }, outlineLevel: 0 },
        },
        {
          id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
          run: { size: 26, bold: true, font: 'Arial', color: DARK },
          paragraph: { spacing: { before: 300, after: 80 }, outlineLevel: 1 },
        },
      ],
    },
    sections: [{
      properties: {
        page: {
          size: { width: PAGE_W, height: PAGE_H },
          margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN },
        },
      },
      headers: {
        default: new Header({ children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RED, space: 4 } },
          children: [
            new TextRun({ text: 'TiDB Cloud  \u2014  The Database for the Agent Era   |   ', font: 'Arial', size: 16, color: MUTED }),
            new TextRun({ text: 'CONFIDENTIAL  \u2014  PingCAP', font: 'Arial', size: 16, bold: true, color: RED }),
          ],
        })] }),
      },
      footers: {
        default: new Footer({ children: [new Paragraph({
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: RED, space: 4 } },
          alignment: AlignmentType.RIGHT,
          children: [
            new TextRun({ text: 'TiDB Cloud Pitch & Demo  |  GTM Playbook Edition  |  Page ', font: 'Arial', size: 16, color: MUTED }),
            new TextRun({ children: [PageNumber.CURRENT], font: 'Arial', size: 16, color: MUTED }),
          ],
        })] }),
      },
      children: [
        ...coverSection(),
        ...strategicContextSection(),
        new Paragraph({ children: [new PageBreak()] }),
        ...elevatorSection(),
        new Paragraph({ children: [new PageBreak()] }),
        ...fullDemoSection(),
        new Paragraph({ children: [new PageBreak()] }),
        ...proofPointsSection(),
        new Paragraph({ children: [new PageBreak()] }),
        ...competitiveSection(),
        new Paragraph({ children: [new PageBreak()] }),
        ...demoSetupSection(),
        new Paragraph({ children: [new PageBreak()] }),
        ...qnaSection(),
      ],
    }],
  });

  const outPath = `${__dirname}/TIDB_PITCH_AND_DEMO_SCRIPTS.docx`;
  const buffer  = await Packer.toBuffer(doc);
  fs.writeFileSync(outPath, buffer);
  console.log(`\u2705  Written: ${outPath}`);
}

build().catch(err => { console.error(err); process.exit(1); });
