"""Explicit CSV contract; no spreadsheet executable content is evaluated."""
import csv
import io


def parse_csv(raw):
    text = raw.get('text')
    if not isinstance(text, str) or len(text.encode('utf-8')) > 1024*1024:
        raise ValueError('CSV 不得超过 1 MB')
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), strict=True)
    required = {'title', 'priority', 'layer', 'basis', 'steps', 'expected'}
    if not reader.fieldnames or set(reader.fieldnames) != required or len(reader.fieldnames) != len(required):
        raise ValueError('CSV 表头必须为 title,priority,layer,basis,steps,expected（不可重复或含额外列）')
    cases = []
    try:
        for row in reader:
            if len(cases) >= 500 or None in row or any(not isinstance(v, str) or not v.strip() for v in row.values()):
                raise ValueError(f'第 {reader.line_num} 行字段缺失、多余，或超过 500 条限制')
            row = {k: v.strip() for k, v in row.items()}
            if row['priority'] not in {'P0','P1','P2','P3'} or row['layer'] not in {'手工','UI','API','端侧'}:
                raise ValueError(f'第 {reader.line_num} 行优先级或分层不合法')
            if any(len(v) > (10000 if k in {'steps','expected'} else 1000 if k == 'basis' else 200) for k,v in row.items()):
                raise ValueError(f'第 {reader.line_num} 行内容过长')
            cases.append(row)
    except csv.Error as exc:
        raise ValueError(f'CSV 格式错误：{exc}') from exc
    if not cases:
        raise ValueError('CSV 没有用例')
    return {'cases': cases}
