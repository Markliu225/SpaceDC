# Report layout and preservation record

The retained source documents are Power/SDTwin_Power_Design_Report_CN.docx,
Power/SDTwin_Power_Design_Report_EN.docx and Power/SDTwin_Power_Test_Report_CN.docx.
The first two remain byte identical to design_before. The test source inherits the
Orbit template: cover, revision table, contents, seven numbered chapters and an
eleven-row case form. The new report clones this form, including merged cells,
instead of replacing it with a generic prose report.

The source portrait page is approximately 21.0 by 29.7 cm with 2.54 cm top/bottom
and 3.175 cm left/right margins. Existing design sections, landscape requirements
matrix, headers, footers and numbering remain. Battery paragraphs, P5-P8/P10/P11,
dependent interface rows and two battery flow diagrams are editable. Electrical
topology and solar/distribution equations remain. A new battery estimator appendix
is added. Original versions and parameter failures are retained.

The battery test report uses the existing cover, revision history, Word contents
field and case-record style. Chapter titles match the Orbit-derived source.
Each case has input, initial conditions, purpose, steps, criterion, observed
result, verdict and anomaly record, followed by a figure or numeric table.
Long figures stay with their captions; case forms stay together.

The packaged render_docx.py was attempted and could not find LibreOffice.
Native Word COM updated contents/page fields and exported PDFs. Poppler rendered
all pages. Full-page and contact-sheet review found an incorrect cover date row,
residual lithium symbols in P11, detached figure captions and a final orphan
paragraph; the authoring script was corrected and the artifacts re-exported.
The final audit manifest records page counts, hashes, test outcomes and inspected
render directories. No reviewer name or approval was invented.
