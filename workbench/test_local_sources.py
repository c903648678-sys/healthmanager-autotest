"""A selected original stays on disk and only yields text when requested."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from .contracts import ROOT
from .local_sources import LocalSources


class LocalSourceTests(unittest.TestCase):
    def test_link_metadata_persists_and_original_changes_are_detected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root/'规格.md'
            original.write_text('合成规格正文', encoding='utf-8')
            registry = LocalSources(root/'workspace')
            link, = registry.register([original])
            self.assertNotIn('合成规格正文', registry.path.read_text(encoding='utf-8'))
            reopened = LocalSources(registry.path.parent)
            self.assertEqual(reopened.read(link['localRef'])['text'], '合成规格正文')
            original.write_text('更新后的正文内容', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '已变化'):
                reopened.read(link['localRef'])

    def test_office_and_pdf_are_extracted_only_when_read(self):
        python = ROOT/'api/.venv'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            subprocess.run([str(python), '-c', """
from pathlib import Path
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

d = Document()
d.add_paragraph('Word fixture')
d.save('document.docx')
w = Workbook()
w.active.append(['Excel fixture'])
w.save('table.xlsx')
p = Presentation()
slide = p.slides.add_slide(p.slide_layouts[6])
slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text='PowerPoint fixture'
p.save('slides.pptx')
w = PdfWriter()
page = w.add_blank_page(300,300)
font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
stream = DecodedStreamObject()
stream.set_data(b'BT /F1 12 Tf 30 30 Td (PDF fixture) Tj ET')
page[NameObject('/Contents')] = w._add_object(stream)
w.write('document.pdf')
Path('notes.txt').write_text('Text fixture', encoding='utf-8')
"""], cwd=folder, check=True)
            registry = LocalSources(folder/'workspace')
            links = registry.register(list(folder.iterdir()))
            self.assertEqual(len(links), 5)
            self.assertNotIn('fixture',registry.path.read_text(encoding='utf-8'))
            expected = {'document.docx':'Word','table.xlsx':'Excel','slides.pptx':'PowerPoint',
                        'document.pdf':'PDF','notes.txt':'Text'}
            for link in links:
                document = registry.read(link['localRef'])
                self.assertIn(expected[link['name']]+' fixture',document['text'])
