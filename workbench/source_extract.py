"""Extract text on demand from a selected Office document or PDF."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def extraction_lines(path):
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        from pypdf import PdfReader
        for page in PdfReader(path).pages:
            yield page.extract_text() or ''
    elif suffix == '.docx':
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        for block in Document(path).iter_inner_content():
            if isinstance(block, Paragraph):
                yield block.text
            elif isinstance(block, Table):
                for row in block.rows:
                    yield ' | '.join(cell.text for cell in row.cells)
    elif suffix == '.xlsx':
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            for sheet in workbook:
                yield f'[{sheet.title}]'
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value) if value is not None else '' for value in row]
                    if any(values):
                        yield ' | '.join(values)
        finally:
            workbook.close()
    elif suffix == '.pptx':
        from pptx import Presentation
        for number, slide in enumerate(Presentation(path).slides, 1):
            yield f'[第 {number} 页]'
            for shape in slide.shapes:
                if shape.has_text_frame:
                    yield shape.text
                elif shape.has_table:
                    for row in shape.table.rows:
                        yield ' | '.join(cell.text for cell in row.cells)
    elif suffix in ('.doc', '.xls', '.ppt'):
        soffice = shutil.which('soffice')
        if not soffice and os.name == 'nt':
            installed = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'LibreOffice/program/soffice.exe'
            if installed.is_file():
                soffice = str(installed)
        if not soffice:
            raise ValueError('旧版 Office 格式需要 LibreOffice，或先另存为 DOCX、XLSX 或 PPTX')
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            output = suffix[1:]+'x'
            subprocess.run([soffice, '--headless', '-env:UserInstallation='+ (folder/'profile').as_uri(),
                            '--convert-to', output, '--outdir', temp, str(path)],
                           capture_output=True, check=True, timeout=30)
            yield from extraction_lines(folder/(path.stem+'.'+output))


if __name__ == '__main__':
    from .local_sources import MAX_TEXT
    try:
        lines, length = [], 0
        for line in extraction_lines(Path(sys.argv[1])):
            length += len(line.encode('utf-8')) + 1
            if length > MAX_TEXT:
                raise ValueError('提取文本超过 200 KB，请拆分后再引用')
            lines.append(line)
        sys.stdout.write('\n'.join(lines))
    except ImportError:
        print('缺少文档依赖，请重新运行 python scripts/bootstrap.py --project api')
        sys.exit(1)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)
    except Exception:
        print('无法读取文档，请确认文件完整且未加密')
        sys.exit(1)
