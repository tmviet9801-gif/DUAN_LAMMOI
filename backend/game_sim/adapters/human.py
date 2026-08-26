"""Human-like behavior — tránh bị phát hiện tự động hóa.

- Gõ phím từng ký tự có delay ngẫu nhiên.
- Click với chuyển động chuột (mouse.move steps + delay).
- Di chuyển chuột ngẫu nhiên khi rảnh.
"""
import asyncio
import random


class HumanBehavior:
    @staticmethod
    async def random_delay(min_ms: float = 200, max_ms: float = 800):
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)

    @staticmethod
    async def human_type(page, selector: str, text: str, delay_range=(60, 180)):
        try:
            await page.click(selector)
        except Exception:
            pass
        for ch in str(text):
            await page.keyboard.type(ch, delay=random.randint(*delay_range))
        await HumanBehavior.random_delay(100, 300)

    @staticmethod
    async def human_click(page, selector: str):
        try:
            box = await page.locator(selector).bounding_box()
            if box:
                x = box["x"] + random.uniform(2, max(2, box["width"] - 2))
                y = box["y"] + random.uniform(2, max(2, box["height"] - 2))
                await page.mouse.move(x, y, steps=random.randint(5, 14))
                await asyncio.sleep(random.uniform(0.04, 0.15))
                await page.mouse.click(x, y)
                return True
        except Exception:
            pass
        try:
            await page.click(selector)
            return True
        except Exception:
            return False

    @staticmethod
    async def random_mouse_movement(page, moves: int = 2):
        for _ in range(random.randint(1, moves)):
            try:
                x = random.randint(120, 1400)
                y = random.randint(120, 900)
                await page.mouse.move(x, y, steps=random.randint(8, 20))
                await asyncio.sleep(random.uniform(0.08, 0.3))
            except Exception:
                return
