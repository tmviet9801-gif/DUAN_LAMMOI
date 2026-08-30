import asyncio
import tempfile
from patchright.async_api import async_playwright

EXT = r"C:\Users\Admin\AppData\Local\autotool-min"

async def main():
    async with async_playwright() as p:
        udd = tempfile.mkdtemp(prefix="exttest_")
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=udd,
            headless=False,
            args=[
                "--disable-extensions-except=" + EXT,
                "--load-extension=" + EXT,
            ],
        )
        pg = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await pg.goto("https://example.com", timeout=20000)
        await asyncio.sleep(4)
        sws = [w.url for w in ctx.service_workers]
        print("service_workers:", sws[:5])
        bps = [bp.url for bp in ctx.background_pages]
        print("background_pages:", bps[:5])
        await ctx.close()

asyncio.run(main())
