"""Deterministic spoken answers for product facts supported by Tool results."""

import math
import re


def _offered_sizes(product: dict) -> set[str]:
    return {size.strip().upper().removesuffix("码").removesuffix("号")
            for size in product["sizes"]}


class FactAnswerResolver:
    def resolve(self, question: str, needed: tuple[str, ...], sizes: tuple[str, ...], facts: dict[str, dict]) -> str | None:
        lower = question.lower()
        asks_stock = "stock" in needed
        asks_price = "price" in needed

        if needed == ("product",) and not sizes and "product" in facts:
            product = facts["product"]
            name = product.get("name")
            description = product.get("description")
            offered = [str(size).strip() for size in product.get("sizes", []) if str(size).strip()]
            parts = []
            if isinstance(name, str) and name.strip():
                parts.append(f"这款商品是{name.strip()}")
            else:
                parts.append("这是当前直播商品")
            if isinstance(description, str) and description.strip():
                parts.append(description.strip())
            if offered:
                parts.append("提供的尺码有" + "、".join(offered) + "；尺码选项不代表各尺码有单独库存")
            return "。".join(parts) + "。"

        if len(sizes) == 1 and not asks_price and "product" in facts:
            size = sizes[0]
            offered = size in _offered_sizes(facts["product"])
            if asks_stock:
                if not offered:
                    return f"这款目前没有 {size} 尺码。"
                stock = facts.get("stock", {}).get("stock")
                if type(stock) is int and stock >= 0:
                    overall = "目前商品整体还有库存" if stock > 0 else "目前商品整体库存为零"
                    return f"这款有 {size} 尺码，{overall}，但暂时没有 {size} 单独库存数据。"
                return f"这款有 {size} 尺码，但暂时查不到商品整体库存，也没有 {size} 单独库存数据。"
            if re.search(r"(?:有|提供|卖|支持).*(?:吗|么|？|\?)", lower):
                return f"这款{'有' if offered else '目前没有'} {size} 尺码。"

        if asks_stock and not sizes and not asks_price:
            stock = facts.get("stock", {}).get("stock")
            if type(stock) is int and stock >= 0:
                return f"这款目前商品整体库存还有 {stock} 件。" if stock else "这款目前商品整体库存为 0 件。"

        if asks_price and not asks_stock and not sizes:
            price = facts.get("price", {}).get("price")
            if type(price) in (int, float) and math.isfinite(price) and price >= 0:
                amount = f"{price:g}"
                return f"这款目前价格是 {amount}，币种信息暂不可用。"
        return None
