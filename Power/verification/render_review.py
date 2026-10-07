from pathlib import Path
import sys,json
from pdf2image import convert_from_path
from pypdf import PdfReader
from PIL import Image,ImageDraw
POPPLER=r'C:/Users/markl/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin'
for arg in sys.argv[1:]:
    pdf=Path(arg).resolve();dest=pdf.parent/'verification'/'qa'/pdf.stem;dest.mkdir(parents=True,exist_ok=True)
    for old in [*dest.glob('page*.png'),*dest.glob('contact*.png')]:old.unlink()
    pages=PdfReader(pdf).pages
    inventory=[{'page':i+1,'text':p.extract_text(),'width':float(p.mediabox.width),'height':float(p.mediabox.height)} for i,p in enumerate(pages)]
    (dest/'pages.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    paths=convert_from_path(pdf,dpi=100,output_folder=dest,output_file='page',fmt='png',paths_only=True,poppler_path=POPPLER,thread_count=2)
    for start in range(0,len(paths),6):
        canvas=Image.new('RGB',(1530,2200),'#cacaca');draw=ImageDraw.Draw(canvas)
        for j,path in enumerate(paths[start:start+6]):
            im=Image.open(path).convert('RGB');im.thumbnail((740,690));x=(j%2)*765+10;y=(j//2)*733+30
            canvas.paste(im,(x,y));draw.text((x,y-20),f'Page {start+j+1}',fill='black')
        canvas.save(dest/f'contact-{start//6+1:02}.png')
    print(pdf.name,len(pages),'pages')
