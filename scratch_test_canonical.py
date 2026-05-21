import requests

urls = [
    "https://mercalibreshop.com/cdn/shop/files/ChatGPT_Image_Jan_23_2026_10_33_38_AM.png",
    "https://mercalibreshop.com/cdn/shop/files/36263858831433_66b01564c45aae67c0fcccb1f30136f378583029.gif",
    "https://mercalibreshop.com/cdn/shop/files/ChatGPT_Image_Jan_15_2026_12_59_26_PM_05469656-6e6b-4412-bc89-615226842de3.png"
]

for url in urls:
    try:
        r = requests.head(url, timeout=10)
        print(f"URL: {url} -> Status: {r.status_code}")
    except Exception as e:
        print(f"URL: {url} -> Error: {e}")
