"""规则生成阶段：把人工圈选转成带证据的候选草稿。

生成与执行严格分离：本模块只产出草稿（draft），不修改任何已发布规则；
草稿里每个候选都附带在全部样本上的复算证据，样本互相矛盾时
给出 samples_conflict 未决结果，而不是替运营拍板。
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict

from .candidates import (
    evaluate_on_labels,
    field_candidates,
    record_locator_candidates,
)
from .labio import CANDIDATE_RANK, record_signature
from .samples import group_labels
from .store import canonical_id, save_draft


def _candidate_id(kind, xpath):
    digest = hashlib.sha256(xpath.encode('utf-8')).hexdigest()[:10]
    return f'{kind}-{digest}'


def _build_record_locator(template, pages):
    """选择记录区域定位候选。

    合格条件：在同模板全部样本页命中且包含被圈选的记录，
    同时在其它模板的样本页不命中——否则模板识别会产生歧义，
    这类候选直接降级而不是交给运行期猜。
    """
    labeled_pages = [page for page in pages if page.labeled]
    other_pages = [page for page in pages
                   if page.labeled and page.template != template]
    first_record = labeled_pages[0].labels[0].record
    pool = record_locator_candidates(first_record)
    for locator in pool:
        evidence = []
        covers_all = True
        for page in labeled_pages:
            hits = page.tree.xpath(locator['xpath'])
            includes = any(page.labels[i].record in hits
                           for i in range(len(page.labels)))
            evidence.append({
                'file': page.file,
                'records': len(hits),
                'includes_labeled': includes,
            })
            covers_all = covers_all and includes
        if not covers_all:
            continue
        foreign_hits = []
        for page in other_pages:
            hits = page.tree.xpath(locator['xpath'])
            if hits:
                foreign_hits.append({'file': page.file, 'records': len(hits)})
        if foreign_hits:
            evidence.append({'foreign_templates': foreign_hits})
            continue
        return {
            'kind': locator['kind'],
            'xpath': locator['xpath'],
            'feature': locator['feature'],
            'evidence': evidence,
        }
    return None


def _build_field(template, field, members, locator):
    """合并同组样本产生的候选，按“全样本 + 同页全部记录一致”标准筛选。"""
    record_locators = {page.file: locator['xpath'] for page, _ in members}
    merged = OrderedDict()
    negative_relatives = []
    for _page, label in members:
        for path in label.negative_relatives:
            if path not in negative_relatives:
                negative_relatives.append(path)
        for candidate in field_candidates(label.record, label.positive, label.negatives):
            merged.setdefault(candidate['xpath'], {
                'kind': candidate['kind'],
                'feature': candidate['feature'],
                'xpath': candidate['xpath'],
            })

    survivors, rejected = [], []
    for candidate in merged.values():
        consistent, evidence = evaluate_on_labels(
            candidate, members, record_locators)
        entry = {
            'id': _candidate_id(candidate['kind'], candidate['xpath']),
            'kind': candidate['kind'],
            'feature': candidate['feature'],
            'xpath': candidate['xpath'],
            'evidence': evidence,
        }
        if consistent:
            survivors.append(entry)
        else:
            failures = [item for item in evidence if item['status'] != 'unique']
            entry['reason'] = '；'.join(
                f"{item['file']} 上 {item['status']}" for item in failures)
            rejected.append(entry)

    survivors.sort(key=lambda item: CANDIDATE_RANK[item['kind']])
    rejected.sort(key=lambda item: CANDIDATE_RANK[item['kind']])
    status = 'consistent' if survivors else 'samples_conflict'
    return {
        'status': status,
        'negative': negative_relatives,
        'candidates': survivors,
        'rejected': rejected,
        'sample_count': len(members),
    }


def build_draft(pages, source_name):
    grouped = group_labels(pages)
    templates = OrderedDict()
    template_names = sorted({page.template for page in pages if page.labeled})
    for template in template_names:
        template_pages = [page for page in pages if page.template == template]
        locator = _build_record_locator(template, template_pages)
        if locator is None:
            raise ValueError(f'模板 {template} 的记录区域在样本间无法一致定位，规则生成中止')
        signature_record = next(
            page.labels[0].record for page in template_pages if page.labeled)
        fields = OrderedDict()
        for (tpl, field), members in sorted(grouped.items()):
            if tpl != template:
                continue
            fields[field] = _build_field(template, field, members, locator)
        templates[template] = {
            'record_locator': locator,
            'record_signature': list(record_signature(signature_record)),
            'fields': fields,
        }

    draft = {
        'schema': 'selector-lab/draft/v1',
        'sources': {
            'annotations': source_name,
            'pages': sorted({page.file for page in pages}),
        },
        'templates': templates,
    }
    draft['id'] = canonical_id(draft)
    return draft


def generate(pages, source_name, lab_home):
    draft = build_draft(pages, source_name)
    return save_draft(lab_home, draft)
