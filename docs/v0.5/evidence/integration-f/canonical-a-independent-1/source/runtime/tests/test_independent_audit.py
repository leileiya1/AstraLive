import unittest
from app.session import mentioned_sizes, required_product_facts
from app.fact_answer import FactAnswerResolver
from app.real_tts import spoken_sizes


class IndependentAuditTests(unittest.TestCase):
    def test_2xl_is_a_size_fact_request(self):
        self.assertEqual(mentioned_sizes('2XL 有吗？'), ('2XL',))
        self.assertEqual(required_product_facts('2XL 有吗？'), ('product',))
        facts = {'product': {'sizes': ['XL', 'XXL', '2XL']}, 'stock': {'stock': 27}}
        answer = FactAnswerResolver().resolve('2XL 库存多少？', ('product', 'stock'), mentioned_sizes('2XL 库存多少？'), facts)
        self.assertIn('没有 2XL 单独库存数据', answer)
        self.assertNotIn('库存还有 27 件', answer)

    def test_pronunciation_keeps_model_units_and_price(self):
        for text in ('型号 AB-2XL-Pro；500毫升，129.90元。',
                     'XL500 型号，长度 20 M，容量 500 ML。',
                     '英文 XL is a model identifier. 中文混合。'):
            self.assertEqual(spoken_sizes(text), text)
        self.assertEqual(spoken_sizes('XXL 尺码和 2XL 单码库存'),
                         '艾克斯艾克斯艾尔 尺码和 艾克斯艾克斯艾尔 单码库存')

    def test_size_list_does_not_convert_following_units_or_model(self):
        self.assertEqual(spoken_sizes('尺码有 XL、XXL，型号 S，长度 20 M，容量 5 L，价格 129.90元。'),
                         '尺码有 艾克斯艾尔、艾克斯艾克斯艾尔，型号 S，长度 20 M，容量 5 L，价格 129.90元。')
