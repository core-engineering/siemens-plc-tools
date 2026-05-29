# Example project — "Example Plant"

A minimal generic project demonstrating the siemens-plc-tools SCL toolchain on
six example function blocks (motor starter, pump control, conveyor mode, valve
control, tank level monitor, and signal debounce).

## Layout

```
demo-project/
  plc.yaml              # unified config (code: and iol: sections)
  program-blocks/       # six example .s7dcl SCL blocks
  tags/                 # example TIA Portal tag table (ExampleTags.xml)
  tests/                # unit tests (create this dir and add test_*.py here)
  docs/                 # generated documentation (git-ignored)
  .iol/                 # generated I/O database cache (git-ignored)
  pdf-template/         # neutral custom PDF template (optional, see below)
```

## Try it

```bash
cd examples/demo-project

plc code lint                      # quality analysis of the SCL blocks
plc code docs                      # generate MkDocs documentation (output is git-ignored)
plc code test                      # run the SCL unit tests (none yet — exits cleanly)
plc iol import tags --path tags    # import the example I/O tags
plc code export pdf -o report.pdf  # PDF report (requires pandoc + xelatex)
```

## Custom PDF template

`plc code export pdf` accepts a `--template-dir` flag pointing at a directory
that supplies a custom LaTeX template (and, optionally, images). This example
ships a neutral, brand-free template under `pdf-template/`:

```
pdf-template/
  01_Header.md             # example eisvogel-style frontmatter (reference)
  02_Introduction.md       # example introduction part (reference)
  Templates/template.tex   # self-contained pandoc LaTeX template (no external assets)
  Images/                  # drop optional logo/background images here
```

Generate the report with the custom template:

```bash
plc code export pdf -o report.pdf --template-dir pdf-template
```

`Templates/template.tex` is a minimal, standalone pandoc template: it renders a
title page, table of contents, and body with `xelatex` and references no
external image or binary asset, so it compiles out of the box. Copy it into
your own project and adapt it to your house style (fonts, colours, header,
footer, logo). To add a logo or title-page background, place the image file in
`pdf-template/Images/` and reference it from `Templates/template.tex`.

The generated `docs/`, `site/`, and `.iol/` outputs are git-ignored; only the
source files (`plc.yaml`, `README.md`, `program-blocks/*.s7dcl`,
`tags/ExampleTags.xml`, `pdf-template/`) are tracked.
