"""日常执行：只使用已发布且激活的不可变规则包。

执行与生成互不写对方的数据；运行结果携带规则包 id，同一版 pack
对同一页面必然得到同一版定位。任何歧义（多命中、无命中、负例、
结构漂移、模板拿不准）都返回 undecided，不输出可能是划线原价的值。
"""
from __future__ import annotations

from .labio import node_path, record_signature, relative_path, text_preview


def _detect_template(tree, pack):
    matches = []
    for name, body in pack['templates'].items():
        hits = tree.xpath(body['record_locator']['xpath'])
        if hits:
            matches.append((name, hits))
    if not matches:
        return None, [], 'template_no_match'
    if len(matches) > 1:
        return None, [name for name, _ in matches], 'template_ambiguous'
    name, hits = matches[0]
    return name, hits, 'matched'


def run_page(tree, pack, file_name='<memory>'):
    template, records, detect_status = _detect_template(tree, pack)
    result = {
        'file': file_name,
        'pack_id': pack['id'],
        'template_detected': template,
        'detection': detect_status,
        'records': [],
    }
    if detect_status != 'matched':
        result['verdict'] = 'undecided'
        result['reason'] = detect_status
        return result

    body = pack['templates'][template]
    expected_signature = tuple(tuple(item) for item in body['record_signature'])
    page_verdict = 'ok'
    for index, record in enumerate(records):
        record_result = {
            'index': index,
            'dom_path': node_path(tree, record),
            'structure_drift': record_signature(record) != expected_signature,
            'fields': {},
        }
        if record_result['structure_drift']:
            page_verdict = 'undecided'
        for field, rule in body['fields'].items():
            hits = record.xpath(rule['xpath'])
            negative_paths = set(rule['negative'])
            hit_paths = [relative_path(record, node) for node in hits]
            if not hits:
                status, value, reason = 'undecided', None, 'no_hit'
            elif len(hits) > 1:
                status, value, reason = 'undecided', None, 'multi_hit'
            elif hit_paths[0] in negative_paths:
                status, value, reason = 'undecided', None, 'negative_hit'
            elif record_result['structure_drift']:
                status, value, reason = 'undecided', None, 'structure_drift'
            else:
                status, value, reason = 'ok', text_preview(hits[0]), None
            record_result['fields'][field] = {
                'status': status,
                'reason': reason,
                'value': value,
                'dom_path': hit_paths[0] if hit_paths else None,
                'candidate_id': rule['candidate_id'],
            }
            if status == 'undecided':
                page_verdict = 'undecided'
        result['records'].append(record_result)
    result['verdict'] = page_verdict
    return result
