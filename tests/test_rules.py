"""规则生成、歧义检出与发布边界的测试。

全部使用临时目录内的本地页面，不发起任何网络请求；
断言聚焦业务承诺：负例约束、拒绝歧义、版本不可变。
"""
import json
from pathlib import Path
import tempfile
import unittest

from selector_lab.candidates import field_candidates
from selector_lab.execute import run_page
from selector_lab.generate import build_draft
from selector_lab.labio import load_tree, relative_path
from selector_lab.samples import load_bundle
from selector_lab.store import (
    activate_pack,
    load_draft,
    load_pack,
    publish_pack,
)
from selector_lab.verify import verify_pages

LIST_HTML = (
    '<html lang="zh-CN"><head><meta charset="utf-8"></head><body>'
    '<section class="catalog">'
    '<article data-sku="A"><h2>滤芯甲</h2><del>￥200</del>'
    '<strong class="price">￥160</strong></article>'
    '<article data-sku="B"><h2>滤芯乙</h2><del>￥240</del>'
    '<strong class="price">￥180</strong></article>'
    '</section></body></html>'
)

# 布局扰动：旧价节点抢到了 price 类，真实售价改用 data-price 标记
CHANGED_HTML = (
    '<html lang="zh-CN"><head><meta charset="utf-8"></head><body>'
    '<section class="catalog">'
    '<article data-sku="C"><div class="banner">立减20</div><h2>滤芯丙</h2>'
    '<strong class="price old">￥300</strong>'
    '<strong data-price="current">￥220</strong></article>'
    '</section></body></html>'
)

ANNOTATIONS = {
    'pages': [
        {'file': 'list.html', 'template': 'list', 'labels': [
            {'field': 'price', 'record': '//*[@data-sku="A"]',
             'positive': './/strong', 'negative': ['.//del']}]},
    ]
}


class LabCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'list.html').write_text(LIST_HTML, encoding='utf-8')
        (self.root / 'changed.html').write_text(CHANGED_HTML, encoding='utf-8')
        (self.root / 'annotations.json').write_text(
            json.dumps(ANNOTATIONS, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def pages(self):
        return load_bundle(self.root / 'annotations.json')

    def draft(self):
        pages = self.pages()
        return build_draft(pages, 'annotations.json')


class GenerationTests(LabCase):
    def test_relative_position_uses_nth_child_semantics(self):
        pages = self.pages()
        label = pages[0].labels[0]
        path = relative_path(label.record, label.positive)
        # strong 是第三个元素子节点，不能写成会按“第几个 strong”计数的 ./strong[3]
        self.assertEqual(path, "./*[3][name()='strong']")
        self.assertEqual(label.record.xpath(path), [label.positive])

    def test_negative_node_never_becomes_anchor_or_candidate(self):
        pages = self.pages()
        label = pages[0].labels[0]
        candidates = field_candidates(label.record, label.positive, label.negatives)
        for candidate in candidates:
            hits = label.record.xpath(candidate['xpath'])
            self.assertNotIn(label.negatives[0], hits,
                             f'候选命中了负例节点: {candidate["xpath"]}')
        features = ' '.join(c['feature'] for c in candidates)
        self.assertNotIn('￥200', features)

    def test_record_locator_generalizes_attribute_value(self):
        draft = self.draft()
        xpath = draft['templates']['list']['record_locator']['xpath']
        # 只要求属性存在，不绑定具体 SKU，换商品后仍能定位
        self.assertNotIn('"A"', xpath)
        tree = load_tree(self.root / 'changed.html')
        self.assertEqual(len(tree.xpath(xpath)), 1)

    def test_draft_is_content_addressed_and_idempotent(self):
        first = self.draft()
        second = self.draft()
        self.assertEqual(first['id'], second['id'])


class VerificationTests(LabCase):
    def test_changed_page_is_undecided_and_shows_drift(self):
        draft = self.draft()
        (self.root / 'annotations.json').write_text(json.dumps({
            'pages': ANNOTATIONS['pages'] + [
                {'file': 'changed.html', 'template': 'list', 'labels': []}]
        }, ensure_ascii=False), encoding='utf-8')
        report = verify_pages(self.pages(), draft)
        changed = next(p for p in report['pages'] if p['file'] == 'changed.html')
        self.assertEqual(changed['verdict'], 'undecided')
        record = changed['records'][0]
        self.assertTrue(record['structure_drift'])
        # 每个候选都展示实际 DOM 位置，运营能看到谁误选了 ￥300
        price = record['fields']['price']
        self.assertIn(price['verdict'], {'multi_hit', 'candidate_disagreement'})
        texts = {node['text'] for c in price['candidates'] for node in c['nodes']}
        self.assertIn('￥300', texts)


class PublishAndRunTests(LabCase):
    def _publish(self, lab):
        draft = self.draft()
        report = draft['templates']['list']['fields']['price']
        chosen = report['candidates'][0]['id']
        info = publish_pack(lab, draft, {'list/price': chosen})
        return draft, info

    def test_publish_requires_explicit_choice_when_ambiguous(self):
        draft = self.draft()
        with tempfile.TemporaryDirectory() as lab:
            with self.assertRaises(ValueError):
                publish_pack(Path(lab), draft, {})

    def test_published_pack_runs_clean_page_but_refuses_drift(self):
        with tempfile.TemporaryDirectory() as lab:
            lab = Path(lab)
            _, info = self._publish(lab)
            activate_pack(lab, info['id'])
            pack = load_pack(lab)

            good = run_page(load_tree(self.root / 'list.html'), pack, 'list.html')
            self.assertEqual(good['verdict'], 'ok')
            self.assertEqual(good['records'][0]['fields']['price']['value'], '￥160')

            changed = run_page(load_tree(self.root / 'changed.html'), pack, 'changed.html')
            self.assertEqual(changed['verdict'], 'undecided')
            self.assertIsNone(changed['records'][0]['fields']['price']['value'])

    def test_tampered_pack_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Path(directory)
            _, info = self._publish(lab)
            pack_path = lab / 'packs' / f"{info['id']}.json"
            data = json.loads(pack_path.read_text(encoding='utf-8'))
            data['templates']['list']['fields']['price']['xpath'] = './/del'
            pack_path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_pack(lab)

    def test_new_labels_do_not_mutate_published_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Path(directory)
            _, info = self._publish(lab)
            before = (lab / 'packs' / f"{info['id']}.json").read_bytes()
            # 追加一个新字段标签，重新生成草稿
            data = json.loads((self.root / 'annotations.json').read_text(encoding='utf-8'))
            data['pages'][0]['labels'].append(
                {'field': 'title', 'record': '//*[@data-sku="A"]',
                 'positive': './/h2', 'negative': ['.//del']})
            (self.root / 'annotations.json').write_text(
                json.dumps(data, ensure_ascii=False), encoding='utf-8')
            build_draft(self.pages(), 'annotations.json')
            after = (lab / 'packs' / f"{info['id']}.json").read_bytes()
            self.assertEqual(before, after)


class ContradictionTests(LabCase):
    def test_conflicting_samples_block_publication(self):
        second = (
            '<html lang="zh-CN"><head><meta charset="utf-8"></head><body>'
            '<article data-sku="Z"><em class="price">￥99</em>'
            '<del>￥120</del></article></body></html>'
        )
        (self.root / 'second.html').write_text(second, encoding='utf-8')
        (self.root / 'conflict.json').write_text(json.dumps({
            'pages': [
                {'file': 'list.html', 'template': 'list', 'labels': [
                    {'field': 'price', 'record': '//*[@data-sku="A"]',
                     'positive': './/strong', 'negative': ['.//del']}]},
                {'file': 'second.html', 'template': 'list', 'labels': [
                    {'field': 'price', 'record': '//*[@data-sku="Z"]',
                     'positive': './/em', 'negative': ['.//del']}]},
            ]}, ensure_ascii=False), encoding='utf-8')
        pages = load_bundle(self.root / 'conflict.json')
        draft = build_draft(pages, 'conflict.json')
        report = draft['templates']['list']['fields']['price']
        self.assertEqual(report['status'], 'samples_conflict')
        self.assertEqual(report['candidates'], [])
        with tempfile.TemporaryDirectory() as lab:
            with self.assertRaises(ValueError):
                publish_pack(Path(lab), draft, {})


class EncodingTests(LabCase):
    def test_utf8_is_default_without_charset_declaration(self):
        # 页面不声明 charset 时，中文文本锚点也不能解成乱码
        raw = LIST_HTML.replace('<head><meta charset="utf-8"></head>', '')
        (self.root / 'nocharset.html').write_bytes(raw.encode('utf-8'))
        tree = load_tree(self.root / 'nocharset.html')
        strong = tree.xpath('//strong')[0]
        self.assertEqual(' '.join(strong.itertext()), '￥160')


if __name__ == '__main__':
    unittest.main()
