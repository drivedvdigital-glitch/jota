import asyncio
from playwright.async_api import async_playwright

async def inspect():
    url = "https://mercalibreshop.com/collections/hogar/products/extensor-de-grifo-para-bano"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="networkidle")
        
        # Run the same image extraction logic
        candidate_images = await page.evaluate("""() => {
            const gallerySelectors = [
                '.product-single__photos', '.product-single__media', 
                '.product__media-list', '.product__media-item',
                '.product-images', '.media-gallery', '.gallery',
                '.product__images', '.slider__slide', '.carousel'
            ];
            
            let imgs = [];
            for (const sel of gallerySelectors) {
                const containers = document.querySelectorAll(sel);
                if (containers.length > 0) {
                    containers.forEach(container => {
                        const foundImgs = Array.from(container.querySelectorAll('img'));
                        foundImgs.forEach(img => {
                            const src = img.src || img.dataset.src || img.dataset.lazySrc;
                            if (src && src.startsWith('http')) {
                                imgs.push({
                                    src: src,
                                    tagName: img.tagName,
                                    className: img.className,
                                    id: img.id,
                                    parentClass: img.parentElement ? img.parentElement.className : ''
                                });
                            }
                        });
                    });
                }
            }
            return imgs;
        }""")
        
        print(f"\nFound {len(candidate_images)} raw images:")
        for idx, img in enumerate(candidate_images):
            print(f"[{idx}] src: {img['src']}")
            print(f"    parentClass: {img['parentClass']}")
            print(f"    className: {img['className']}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
