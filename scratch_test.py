from main import clean_price

test_cases = [
    "COP 607,230.00",
    "607,230.00",
    "R$ 1.234,56",
    "1.234,56",
    "607.230",
    "COP 607.230",
    "607,230",
    "607230",
    "607230.00",
    "607230,00",
    "12.990",
    "$ 12.990",
    "12,990",
    "12.99",
    "12,99"
]

print("Starting clean_price testing...")
for tc in test_cases:
    res = clean_price(tc)
    print(f"'{tc}' => '{res}'")

