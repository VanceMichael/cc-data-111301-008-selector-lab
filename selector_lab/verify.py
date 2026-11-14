"""对未参与生成的页面做候选验证。

输出可检查的覆盖情况与实际 DOM 位置：模板拿不准、多重命中、无命中、
候选之间意见不一致、结构签名漂移，都返回显式未决状态，
不会悄悄选第一个节点。
"""
from __future__ import annotations

from .candidates import evaluate_on_record
from .labio import node_path, record_signature, relative_path, text_preview


def _detect_template(tree, draft):
    matches = []
    for name, body in draft['templates'].items():
        hits = tree.xpath(body['record_locator']['xpath'])
        if hits:
            matches.append((name, hits))
    if not matches:
        return None, [], 'template_no_match'
    if len(matches) > 1:
        return None, [name for name, _ in matches], 'template_ambiguous'
    name, hits = matches[0]
    return name, hits, 'matched'


def _node_descriptions(record, paths):
    descriptions = []
    for node in record.iter():
        if relative_path(record, node) in paths:
            descriptions.append({
                'relative': relative_path(record, node),
                'text': text_preview(node),
            })
    return descriptions


def verify_pages(pages, draft):
    results = []
    for page in pages:
        template, records, detect_status = _detect_template(page.tree, draft)
        page_result = {
            'file': page.file,
            'template_claim': page.template,
            'template_detected': template,
            'detection': detect_status,
            'records': [],
        }
        if detect_status != 'matched':
            page_result['verdict'] = 'template_uncertain'
            results.append(page_result)
            continue
        body = draft['templates'][template]
        expected_signature = tuple(tuple(item) for item in body['record_signature'])
        page_verdict = 'covered'
        for index, record in enumerate(records):
            drifted = record_signature(record) != expected_signature
            record_result = {
                'index': index,
                'dom_path': node_path(page.tree, record),
                'structure_drift': drifted,
                'fields': {},
            }
            for field, report in body['fields'].items():
                candidate_results = []
                for candidate in report['candidates']:
                    outcome = evaluate_on_record(
                        candidate, record, report['negative'])
                    outcome['candidate_id'] = candidate['id']
                    outcome['kind'] = candidate['kind']
                    outcome['feature'] = candidate['feature']
                    outcome['xpath'] = candidate['xpath']
                    outcome['nodes'] = _node_descriptions(record, outcome['nodes'])
                    candidate_results.append(outcome)

                statuses = {item['status'] for item in candidate_results}
                if statuses == {'no_hit'}:
                    verdict = 'no_hit'
                elif 'multi_hit' in statuses:
                    verdict = 'multi_hit'
                elif 'negative_hit' in statuses:
                    verdict = 'negative_hit'
                else:
                    unique = [item for item in candidate_results
                              if item['status'] == 'unique']
                    node_sets = {
                        tuple(node['relative'] for node in item['nodes'])
                        for item in unique
                    }
                    verdict = ('unique_agreement' if len(node_sets) <= 1
                               else 'candidate_disagreement')
                record_result['fields'][field] = {
                    'verdict': verdict,
                    'candidates': candidate_results,
                }
                if verdict != 'unique_agreement':
                    page_verdict = 'undecided'
            if drifted:
                page_verdict = 'undecided' if page_verdict == 'covered' else page_verdict
                record_result['note'] = '记录结构签名与生成样本不一致，需人工确认布局扰动'
            record_result['verdict'] = (
                'undecided' if any(
                    item['verdict'] != 'unique_agreement'
                    for item in record_result['fields'].values()) or drifted
                else 'ok')
            page_result['records'].append(record_result)
        page_result['verdict'] = page_verdict
        results.append(page_result)
    return {
        'schema': 'selector-lab/verification/v1',
        'draft_id': draft['id'],
        'pages': results,
    }
