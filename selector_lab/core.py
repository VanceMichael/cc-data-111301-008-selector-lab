import json
from pathlib import Path
from lxml import html


def inspect_file(path):
    path = Path(path)
    value = json.loads(path.read_text(encoding='utf-8'))
    pages = []
    for entry in value['pages']:
        tree = html.fromstring((path.parent / entry['file']).read_bytes())
        pages.append({'file':entry['file'],'template':entry['template'],'nodes':len(tree.xpath('//*')),
                      'labels':len(entry['labels'])})
    return {'pages':pages}
