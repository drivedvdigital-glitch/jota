import asyncio
from playwright.async_api import async_playwright

async def explore():
    url = "https://mercalibreshop.com/collections/hogar/products/extensor-de-grifo-para-bano"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="networkidle")
        
        # Let's find common selectors or the main content
        # We can evaluate some javascript to find candidate description containers
        results = await page.evaluate("""() => {
            const candidates = [];
            
            // Check common description classes/ids
            const selectors = [
                '.product-description', '.product-single__description', 
                '#product-description', '.description', '[itemprop="description"]',
                '.rte', '.product__description', '.product-details'
            ];
            
            selectors.forEach(sel => {
                const el = document.querySelector(sel);
                if (el) {
                    candidates.push({
                        selector: sel,
                        htmlLength: el.innerHTML.length,
                        textLength: el.innerText.length,
                        imagesCount: el.querySelectorAll('img').length
                    });
                }
            });
            
            // Also let's find all images/gifs inside the body
            const allImages = Array.from(document.querySelectorAll('img')).map(img => ({
                src: img.src,
                alt: img.alt,
                w: img.naturalWidth || img.width || 0,
                h: img.naturalHeight || img.height || 0
            }));
            
            return {
                candidates,
                allImages: allImages.filter(img => img.src && (img.src.includes('.gif') || (img.w > 150 && img.h > 150)))
            };
        }""")
        
        desc_html = await page.evaluate("""() => {
            const el = document.querySelector('.product-description');
            return el ? el.innerHTML : '';
        }""")

        # Write the HTML of .product-description to a file in UTF-8
        with open("desc_raw.html", "w", encoding="utf-8") as f:
            f.write(desc_html)
        print("Successfully wrote description HTML to desc_raw.html")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(explore())



