"""Static demo catalogue for "Shree Ganesh SuperMart", Pune (spec section 11)."""

from datetime import date

BUSINESS = {
    "name": "Shree Ganesh SuperMart",
    "address": "Shop 4-7, Karve Road, Kothrud",
    "city": "Pune",
    "state": "Maharashtra",
    "gstin": "27AAPFS1234K1Z5",
    "phone": "020-25431234",
    "email": "accounts@shreeganeshmart.in",
}

USERS = [
    # (name, email, password, role, supplier_index)
    ("Ganesh Kulkarni", "admin@demo.in", "Admin@123", "admin", None),
    ("Priya Deshmukh", "manager@demo.in", "Manager@123", "manager", None),
    ("Rohit Pawar", "staff@demo.in", "Staff@123", "staff", None),
    ("Sanjay Agarwal", "supplier1@demo.in", "Supplier@123", "supplier", 0),
    ("Meena Shah", "supplier2@demo.in", "Supplier@123", "supplier", 1),
]

LOCATIONS = [("Main Store - Kothrud", "store", "Karve Road, Kothrud, Pune"),
             ("Central Warehouse - Hadapsar", "warehouse", "Industrial Estate, Hadapsar, Pune")]

CATEGORIES = ["Staples", "Dairy", "Beverages", "Snacks", "Personal Care", "Household", "Packaged Food",
              "Fruits & Vegetables"]

# name, unit, hsn, gst, cost, mrp, base_daily_demand, shelf_life_days (None = no expiry), perishable, pack, moq
PRODUCTS: dict[str, list[tuple]] = {
    "Staples": [
        ("India Gate Basmati Rice 5kg", "pack", "1006", 5, 520, 649, 6, 540, False, 4, 4),
        ("Kolam Rice 10kg", "pack", "1006", 5, 610, 720, 4, 540, False, 2, 2),
        ("Aashirvaad Atta 10kg", "pack", "1101", 5, 395, 470, 9, 120, False, 4, 4),
        ("Toor Dal 1kg", "pack", "0713", 5, 128, 165, 14, 270, False, 10, 10),
        ("Moong Dal 1kg", "pack", "0713", 5, 118, 150, 8, 270, False, 10, 10),
        ("Chana Dal 1kg", "pack", "0713", 5, 82, 105, 9, 270, False, 10, 10),
        ("Sugar 1kg", "pack", "1701", 5, 41, 48, 30, 720, False, 25, 25),
        ("Tata Salt 1kg", "pack", "2501", 0, 22, 28, 22, 720, False, 25, 25),
        ("Fortune Sunflower Oil 1L", "pack", "1512", 5, 128, 155, 18, 270, False, 12, 12),
        ("Dhara Mustard Oil 1L", "pack", "1514", 5, 148, 180, 7, 270, False, 12, 12),
        ("Poha (Thick) 500g", "pack", "1904", 5, 28, 38, 11, 180, False, 20, 20),
        ("Premium Extra Virgin Olive Oil 1L", "pack", "1509", 5, 690, 899, 0.8, 540, False, 6, 6),
    ],
    "Dairy": [
        ("Amul Taaza Toned Milk 500ml", "pcs", "0401", 0, 25, 28, 70, 3, True, 24, 24),
        ("Gokul Full Cream Milk 1L", "pcs", "0401", 0, 62, 68, 28, 3, True, 12, 12),
        ("Amul Masti Dahi 400g", "pcs", "0403", 5, 30, 36, 22, 10, True, 12, 12),
        ("Amul Fresh Paneer 200g", "pcs", "0406", 5, 74, 90, 12, 7, True, 10, 10),
        ("Amul Butter 100g", "pcs", "0405", 12, 49, 58, 14, 120, False, 20, 20),
        ("Amul Cheese Slices 200g", "pcs", "0406", 12, 118, 140, 6, 180, False, 10, 10),
        ("Chitale Shrikhand 500g", "pcs", "0406", 5, 105, 130, 5, 15, True, 6, 6),
        ("Amul Ghee 1L", "pcs", "0405", 12, 520, 610, 3, 270, False, 6, 6),
        ("Nestle a+ Lassi 200ml", "pcs", "0403", 12, 18, 25, 10, 30, True, 24, 24),
    ],
    "Beverages": [
        ("Tata Tea Gold 500g", "pack", "0902", 5, 228, 280, 9, 540, False, 12, 12),
        ("Brooke Bond Red Label 250g", "pack", "0902", 5, 112, 140, 8, 540, False, 12, 12),
        ("Nescafe Classic 100g", "pack", "0901", 18, 295, 350, 4, 540, False, 6, 6),
        ("Bru Instant Coffee 50g", "pack", "0901", 18, 128, 160, 4, 540, False, 12, 12),
        ("Real Mixed Fruit Juice 1L", "pcs", "2009", 12, 98, 125, 8, 180, False, 12, 12),
        ("Coca-Cola 750ml", "pcs", "2202", 18, 32, 40, 18, 180, False, 24, 24),
        ("Thums Up 2L", "pcs", "2202", 18, 78, 95, 9, 180, False, 9, 9),
        ("Bisleri Water 1L", "pcs", "2201", 18, 14, 20, 35, 365, False, 12, 12),
        ("Bournvita 500g", "pack", "1806", 18, 205, 245, 4, 365, False, 6, 6),
        ("Rooh Afza 750ml", "pcs", "2106", 12, 148, 180, 3, 365, False, 6, 6),
    ],
    "Snacks": [
        ("Haldiram Aloo Bhujia 400g", "pack", "2106", 12, 88, 110, 12, 150, False, 12, 12),
        ("Chitale Bakarwadi 250g", "pack", "2106", 12, 82, 105, 9, 60, False, 10, 10),
        ("Lay's Classic Salted 52g", "pcs", "2005", 12, 16, 20, 35, 120, False, 48, 48),
        ("Kurkure Masala Munch 90g", "pcs", "2005", 12, 16, 20, 28, 120, False, 48, 48),
        ("Parle-G Biscuits 800g", "pack", "1905", 18, 76, 90, 14, 180, False, 12, 12),
        ("Britannia Good Day 200g", "pack", "1905", 18, 32, 40, 16, 180, False, 24, 24),
        ("Oreo Chocolate 120g", "pack", "1905", 18, 30, 37, 12, 180, False, 24, 24),
        ("Cadbury Dairy Milk Silk 60g", "pcs", "1806", 18, 70, 85, 10, 270, False, 24, 24),
        ("Kaju Katli 250g", "pack", "1704", 5, 220, 290, 3, 20, True, 5, 5),
        ("Imported Belgian Dark Chocolate 100g", "pcs", "1806", 18, 280, 399, 0.6, 365, False, 10, 10),
    ],
    "Personal Care": [
        ("Dove Cream Beauty Bar 100g", "pcs", "3401", 18, 48, 62, 12, None, False, 24, 24),
        ("Lifebuoy Total 10 Soap 125g", "pcs", "3401", 18, 28, 36, 18, None, False, 48, 48),
        ("Colgate Strong Teeth 200g", "pcs", "3306", 18, 98, 120, 14, None, False, 24, 24),
        ("Clinic Plus Shampoo 340ml", "pcs", "3305", 18, 168, 210, 6, None, False, 12, 12),
        ("Head & Shoulders 180ml", "pcs", "3305", 18, 172, 210, 5, None, False, 12, 12),
        ("Parachute Coconut Oil 500ml", "pcs", "1513", 5, 178, 215, 7, 540, False, 12, 12),
        ("Gillette Guard Razor", "pcs", "8212", 18, 22, 30, 6, None, False, 24, 24),
        ("Dettol Handwash Refill 750ml", "pcs", "3401", 18, 92, 115, 6, None, False, 12, 12),
        ("Whisper Choice Ultra XL 6s", "pack", "9619", 12, 34, 45, 9, None, False, 24, 24),
        ("Kesh King Herbal Hair Oil 300ml", "pcs", "3305", 18, 285, 375, 0.7, None, False, 6, 6),
    ],
    "Household": [
        ("Surf Excel Easy Wash 1kg", "pack", "3402", 18, 118, 145, 12, None, False, 12, 12),
        ("Tide Plus 2kg", "pack", "3402", 18, 198, 240, 7, None, False, 6, 6),
        ("Vim Dishwash Bar 300g", "pcs", "3402", 18, 26, 33, 20, None, False, 48, 48),
        ("Harpic Toilet Cleaner 1L", "pcs", "3808", 18, 158, 195, 6, None, False, 12, 12),
        ("Lizol Floor Cleaner 975ml", "pcs", "3808", 18, 172, 210, 6, None, False, 12, 12),
        ("Good Knight Gold Flash Refill", "pcs", "3808", 18, 68, 85, 9, None, False, 24, 24),
        ("Cycle Agarbatti 3-in-1", "pack", "3307", 5, 48, 60, 11, None, False, 24, 24),
        ("Scotch-Brite Scrub Pad 3s", "pack", "6805", 18, 42, 55, 8, None, False, 24, 24),
        ("Diya Cotton Wicks & Diyas Set", "pack", "6913", 12, 55, 80, 2, None, False, 20, 20),
        ("Rangoli Colours Pack", "pack", "3204", 18, 45, 70, 1.5, None, False, 20, 20),
    ],
    "Packaged Food": [
        ("Maggi 2-Minute Noodles 280g", "pack", "1902", 12, 46, 56, 22, 270, False, 24, 24),
        ("Kissan Tomato Ketchup 950g", "pcs", "2103", 12, 128, 155, 7, 365, False, 12, 12),
        ("Kissan Mixed Fruit Jam 500g", "pcs", "2007", 12, 152, 185, 4, 365, False, 12, 12),
        ("Kellogg's Corn Flakes 475g", "pack", "1904", 18, 168, 205, 5, 270, False, 12, 12),
        ("MTR Ready Upma Mix 500g", "pack", "2106", 12, 92, 115, 4, 180, False, 12, 12),
        ("Everest Garam Masala 100g", "pack", "0910", 5, 72, 90, 8, 365, False, 20, 20),
        ("MDH Kitchen King 100g", "pack", "0910", 5, 74, 92, 6, 365, False, 20, 20),
        ("Saffola Masala Oats 500g", "pack", "1904", 18, 172, 210, 4, 270, False, 12, 12),
        ("Bambino Vermicelli 400g", "pack", "1902", 12, 34, 45, 6, 270, False, 24, 24),
        ("Gits Gulab Jamun Mix 200g", "pack", "2106", 12, 88, 110, 2.5, 270, False, 12, 12),
    ],
    "Fruits & Vegetables": [
        ("Onion (kg)", "kg", "0703", 0, 26, 38, 45, 21, True, 10, 10),
        ("Potato (kg)", "kg", "0701", 0, 22, 32, 40, 21, True, 10, 10),
        ("Tomato (kg)", "kg", "0702", 0, 24, 40, 30, 6, True, 5, 5),
        ("Banana Robusta (dozen)", "dozen", "0803", 0, 38, 55, 18, 5, True, 5, 5),
        ("Shimla Apple (kg)", "kg", "0808", 0, 125, 170, 8, 20, True, 5, 5),
        ("Green Chilli (250g)", "pack", "0709", 0, 12, 20, 15, 5, True, 10, 10),
        ("Coriander Bunch", "pcs", "0709", 0, 8, 15, 25, 3, True, 20, 20),
        ("Lemon (6 pcs)", "pack", "0805", 0, 18, 30, 12, 10, True, 10, 10),
        ("Alphonso Mango Pulp 850g", "pcs", "2008", 12, 145, 185, 2, 365, False, 12, 12),
    ],
}

DEAD_STOCK = {"Premium Extra Virgin Olive Oil 1L", "Imported Belgian Dark Chocolate 100g", "Kesh King Herbal Hair Oil 300ml"}
TREND_UP = {"Saffola Masala Oats 500g", "Bisleri Water 1L", "Amul Fresh Paneer 200g"}
TREND_DOWN = {"Kolam Rice 10kg", "Rooh Afza 750ml"}

# Supplier profiles: name, contact, state, gstin, price_factor (vs base cost), lead_mean, lead_sd, late_prob,
# damage_rate, categories supplied, payment_terms
SUPPLIERS = [
    ("Agarwal Wholesale Traders", "Sanjay Agarwal", "Maharashtra", "27AABFA4321L1Z2", 0.97, 3, 0.8, 0.10, 0.004,
     ["Staples", "Packaged Food", "Snacks"], 30),
    ("Shah Distributors (Ahmedabad)", "Meena Shah", "Gujarat", "24AAKFS9876M1Z8", 0.92, 6, 2.0, 0.38, 0.012,
     ["Staples", "Household", "Personal Care", "Snacks"], 21),
    ("Pune Dairy Fresh Pvt Ltd", "Vikas Jadhav", "Maharashtra", "27AACCP5544D1Z0", 1.00, 1, 0.3, 0.05, 0.010,
     ["Dairy"], 7),
    ("Mahalaxmi Agro Produce", "Sunil Shinde", "Maharashtra", "27AAHFM2211P1Z9", 0.98, 1, 0.4, 0.12, 0.030,
     ["Fruits & Vegetables"], 7),
    ("Reliable FMCG Partners", "Anita Kulkarni", "Maharashtra", "27AAGCR7788F1Z4", 1.07, 2, 0.4, 0.02, 0.002,
     ["Personal Care", "Household", "Beverages", "Packaged Food"], 45),
    ("Karnataka Beverages Co.", "Ravi Gowda", "Karnataka", "29AABCK3344B1Z6", 0.95, 5, 1.2, 0.20, 0.006,
     ["Beverages"], 30),
    ("Delhi Snacks & Sweets House", "Amit Gupta", "Delhi", "07AAFFD6655S1Z3", 0.94, 7, 1.8, 0.30, 0.015,
     ["Snacks", "Packaged Food"], 30),
    ("Chitale Foods Distribution", "Neha Chitale", "Maharashtra", "27AAACC1188H1Z1", 1.02, 2, 0.5, 0.06, 0.004,
     ["Dairy", "Snacks"], 15),
    ("Indore Masala & Spices", "Rajesh Jain", "Madhya Pradesh", "23AAJFI4455K1Z7", 0.90, 6, 1.5, 0.25, 0.010,
     ["Packaged Food", "Staples"], 30),
    ("Om Sai Home Essentials", "Kavita More", "Maharashtra", "27AAOFS9900G1Z5", 1.01, 3, 0.7, 0.08, 0.005,
     ["Household", "Personal Care"], 30),
]

# Festival calendar (spec 7.3). Values: demand multiplier hint and categories that spike.
FESTIVAL_DATES: dict[str, list[date]] = {
    "Diwali": [date(2025, 10, 21), date(2026, 11, 8), date(2027, 10, 29)],
    "Holi": [date(2025, 3, 14), date(2026, 3, 4), date(2027, 3, 22)],
    "Ganesh Chaturthi": [date(2025, 8, 27), date(2026, 9, 14), date(2027, 9, 4)],
    "Navratri": [date(2025, 9, 22), date(2026, 10, 11), date(2027, 9, 30)],
    "Eid al-Fitr": [date(2025, 3, 31), date(2026, 3, 20), date(2027, 3, 10)],
    "Christmas": [date(2025, 12, 25), date(2026, 12, 25), date(2027, 12, 25)],
    "New Year": [date(2025, 1, 1), date(2026, 1, 1), date(2027, 1, 1)],
    "Makar Sankranti": [date(2025, 1, 14), date(2026, 1, 14), date(2027, 1, 14)],
    "Independence Day": [date(2025, 8, 15), date(2026, 8, 15), date(2027, 8, 15)],
}
FESTIVAL_EFFECT: dict[str, tuple[float, int, set[str]]] = {
    # name: (peak multiplier, days of build-up before the date, boosted categories — empty = all)
    "Diwali": (2.6, 6, {"Snacks", "Household", "Dairy", "Staples", "Packaged Food", "Beverages"}),
    "Ganesh Chaturthi": (2.0, 4, {"Dairy", "Snacks", "Staples", "Fruits & Vegetables", "Household"}),
    "Navratri": (1.5, 3, {"Fruits & Vegetables", "Dairy", "Staples"}),
    "Holi": (1.8, 3, {"Beverages", "Snacks", "Household", "Dairy"}),
    "Eid al-Fitr": (1.6, 3, {"Dairy", "Staples", "Packaged Food"}),
    "Christmas": (1.4, 3, {"Snacks", "Beverages", "Dairy"}),
    "New Year": (1.4, 2, {"Beverages", "Snacks"}),
    "Makar Sankranti": (1.5, 2, {"Staples", "Snacks"}),
    "Independence Day": (1.2, 1, {"Snacks", "Beverages"}),
}

APPROVAL_RULES = [(0, 5000, None, True), (5000, 50000, "manager", False), (50000, None, "admin", False)]
