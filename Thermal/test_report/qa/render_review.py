"""Render Word-exported PDFs and make page inventories and contact sheets."""
from pathlib import Path
import json
import sys
from pdf2image import convert_from_path
from pypdf import PdfReader
from PIL import Image, ImageOps, ImageDraw

POPPLER = r'C:\Users\markl\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin'

def render(path):
    dest = path.parent / 'test_report' / 'qa' / path.stem
    dest.mkdir(exist_ok=True)
    # Poppler's threaded prefixes otherwise leave old tail pages when pagination shrinks.
    # This directory is owned by this renderer; remove only its generated PNG files.
    for previous in list(dest.glob('page*.png')) + list(dest.glob('contact-*.png')):
        if previous.resolve().parent != dest.resolve():
            raise RuntimeError(f'Unexpected render path: {previous}')
        previous.unlink()
    reader = PdfReader(path)
    inventory = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ''
        inventory.append({'page': i + 1, 'characters': len(text), 'size': [float(page.mediabox.width), float(page.mediabox.height)],
                          'text': text})
    (dest/'pages.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    paths = convert_from_path(str(path), dpi=100, output_folder=str(dest), fmt='png',
                              output_file='page', paths_only=True, poppler_path=POPPLER, thread_count=2)
    assert len(paths) == len(reader.pages), 'Rendered page count differs from the PDF'
    for start in range(0,len(paths),4):
        canvas=Image.new('RGB',(1280,1860),'#c8c8c8')
        draw=ImageDraw.Draw(canvas)
        for j,p in enumerate(paths[start:start+4]):
            im=Image.open(p).convert('RGB')
            im.thumbnail((620,880))
            x,y=(j%2)*640+10,(j//2)*930+35
            canvas.paste(im,(x,y))
            draw.text((x,y-24),f'Page {start+j+1}',fill='black')
        canvas.save(dest/f'contact-{start//4+1:02}.png')
    print(path.name,len(paths),'pages',dest)

if __name__=='__main__':
    for arg in sys.argv[1:]:render(Path(arg).resolve())
