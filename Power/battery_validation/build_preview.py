"""Compatibility entry point for the current full-cycle and second-scale report."""
from build_current_preview import figures, make_pdf, make_readme

if __name__ == '__main__':
    figures()
    make_pdf()
    make_readme()
