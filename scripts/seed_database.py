"""Seed database script for QueryPilot.

Generates a realistic retail e-commerce database in SQLite:
- customers (~5,000)
- products (~500)
- orders (~50,000)
- order_items (~120,000)
- returns (~6,000)
- warehouses (~10)
- inventory (~2,500)
- marketing_campaigns (~20)
- employees (~50 with salary marked sensitive)
"""

import os
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def create_connection(db_path: str) -> sqlite3.Connection:
    """Create directory if needed and open writable connection."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    return sqlite3.connect(db_path)


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all relational tables and foreign keys."""
    cursor = conn.cursor()

    cursor.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE customers (
        customer_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        city TEXT NOT NULL,
        state TEXT NOT NULL,
        signup_date TEXT NOT NULL,
        segment TEXT NOT NULL
    );

    CREATE TABLE products (
        product_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        sub_category TEXT NOT NULL,
        brand TEXT NOT NULL,
        unit_price REAL NOT NULL,
        cost_price REAL NOT NULL
    );

    CREATE TABLE orders (
        order_id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        order_date TEXT NOT NULL,
        status TEXT NOT NULL,
        payment_method TEXT NOT NULL,
        region TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
    );

    CREATE TABLE order_items (
        item_id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        discount REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    );

    CREATE TABLE returns (
        return_id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        return_date TEXT NOT NULL,
        reason TEXT NOT NULL,
        refund_amount REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    );

    CREATE TABLE warehouses (
        warehouse_id INTEGER PRIMARY KEY,
        city TEXT NOT NULL,
        capacity INTEGER NOT NULL
    );

    CREATE TABLE inventory (
        product_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        stock_qty INTEGER NOT NULL,
        last_restock_date TEXT NOT NULL,
        PRIMARY KEY (product_id, warehouse_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id),
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
    );

    CREATE TABLE marketing_campaigns (
        campaign_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        channel TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        budget REAL NOT NULL
    );

    CREATE TABLE employees (
        employee_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        region TEXT NOT NULL,
        hire_date TEXT NOT NULL,
        salary REAL NOT NULL
    );

    -- Indices for query performance
    CREATE INDEX idx_orders_customer ON orders(customer_id);
    CREATE INDEX idx_orders_date ON orders(order_date);
    CREATE INDEX idx_orders_status ON orders(status);
    CREATE INDEX idx_order_items_order ON order_items(order_id);
    CREATE INDEX idx_order_items_product ON order_items(product_id);
    CREATE INDEX idx_returns_order ON returns(order_id);
    CREATE INDEX idx_returns_product ON returns(product_id);
    CREATE INDEX idx_products_category ON products(category);
    CREATE INDEX idx_customers_state ON customers(state);
    """)
    conn.commit()


def seed_data(conn: sqlite3.Connection) -> None:
    """Populate tables with realistic e-commerce data using fixed random seed."""
    random.seed(42)
    cursor = conn.cursor()

    # 1. Seed Warehouses
    warehouses_data = [
        (1, "Mumbai", 250000),
        (2, "Bengaluru", 200000),
        (3, "Delhi", 220000),
        (4, "Chennai", 180000),
        (5, "Hyderabad", 190000),
        (6, "Pune", 150000),
        (7, "Kolkata", 160000),
        (8, "Ahmedabad", 140000),
        (9, "Jaipur", 120000),
        (10, "Lucknow", 110000),
    ]
    cursor.executemany("INSERT INTO warehouses VALUES (?, ?, ?)", warehouses_data)

    # 2. Seed Customers (~5,000)
    first_names = [
        "Aarav", "Aditi", "Amit", "Ananya", "Arjun", "Deepak", "Divya", "Gaurav", "Isha", "Karan",
        "Kavita", "Manish", "Meera", "Neha", "Nikhil", "Pooja", "Pranav", "Priya", "Rahul", "Rhea",
        "Rohan", "Sanjay", "Shreya", "Siddharth", "Sneha", "Tanvi", "Varun", "Vikram", "Vikas", "Zoya",
    ]
    last_names = [
        "Sharma", "Verma", "Patel", "Mehta", "Deshmukh", "Kulkarni", "Joshi", "Iyer", "Nair", "Reddy",
        "Rao", "Gupta", "Agarwal", "Singh", "Bose", "Chatterjee", "Chopra", "Malhotra", "Kapoor", "Bhat",
    ]
    states_cities = [
        ("Maharashtra", ["Mumbai", "Pune", "Nagpur", "Nashik", "Thane", "Aurangabad"]),
        ("Karnataka", ["Bengaluru", "Mysuru", "Hubballi", "Mangaluru"]),
        ("Delhi", ["New Delhi", "North Delhi", "South Delhi"]),
        ("Tamil Nadu", ["Chennai", "Coimbatore", "Madurai", "Salem"]),
        ("Gujarat", ["Ahmedabad", "Surat", "Vadodara", "Rajkot"]),
        ("Telangana", ["Hyderabad", "Warangal", "Nizamabad"]),
        ("Uttar Pradesh", ["Lucknow", "Noida", "Kanpur", "Varanasi", "Agra"]),
        ("West Bengal", ["Kolkata", "Howrah", "Durgapur"]),
        ("Rajasthan", ["Jaipur", "Jodhpur", "Udaipur"]),
        ("Kerala", ["Kochi", "Thiruvananthapuram", "Kozhikode"]),
    ]
    segments = ["Consumer", "Corporate", "Small Business"]

    start_date = datetime(2022, 1, 1)
    end_date = datetime(2025, 1, 1)
    date_range_days = (end_date - start_date).days

    customers = []
    num_customers = 5000
    for cid in range(1, num_customers + 1):
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        name = f"{fn} {ln}"
        email = f"{fn.lower()}.{ln.lower()}{cid}@example.com"
        state, cities = random.choice(states_cities)
        city = random.choice(cities)
        signup_dt = start_date + timedelta(days=random.randint(0, date_range_days))
        signup_date = signup_dt.strftime("%Y-%m-%d")
        segment = random.choice(segments)
        customers.append((cid, name, email, city, state, signup_date, segment))

    cursor.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)", customers)

    # 3. Seed Products (~500)
    catalog = [
        ("Electronics", "Mobile Phones", ["Apple", "Samsung", "OnePlus", "Xiaomi", "Google"], 20000, 80000),
        ("Electronics", "Laptops", ["Dell", "HP", "Lenovo", "Apple", "Asus"], 40000, 150000),
        ("Electronics", "Audio & Headphones", ["Sony", "Bose", "JBL", "Boat", "Sennheiser"], 1500, 25000),
        ("Electronics", "Smartwatches", ["Apple", "Samsung", "Garmin", "Fitbit", "Noise"], 2000, 35000),
        ("Clothing", "Men's Apparel", ["Levi's", "Zara", "Nike", "Adidas", "Puma"], 800, 5000),
        ("Clothing", "Women's Apparel", ["H&M", "Zara", "Biba", "Fabindia", "AND"], 900, 6000),
        ("Clothing", "Footwear", ["Nike", "Adidas", "Puma", "Bata", "Clarks"], 1200, 9000),
        ("Home & Kitchen", "Cookware", ["Prestige", "Hawkins", "Pigeon", "Wonderchef"], 1000, 8000),
        ("Home & Kitchen", "Appliances", ["Philips", "Bajaj", "Morphy Richards", "Usha"], 1500, 12000),
        ("Home & Kitchen", "Furniture", ["IKEA", "Godrej Interio", "Urban Ladder", "Wakefit"], 3000, 30000),
        ("Books", "Fiction", ["Penguin", "HarperCollins", "Bloomsbury", "Rupa"], 250, 900),
        ("Books", "Non-Fiction", ["Harvard Press", "Rupa", "Penguin", "Routledge"], 350, 1200),
        ("Beauty", "Skincare", ["L'Oreal", "Neutrogena", "Minimalist", "The Ordinary", "Plum"], 400, 2500),
        ("Beauty", "Haircare", ["Dove", "TRESemme", "L'Oreal", "Matrix", "Kama Ayurveda"], 300, 2000),
    ]

    products = []
    pid = 1
    num_products = 500
    while pid <= num_products:
        cat, subcat, brands, min_p, max_p = random.choice(catalog)
        brand = random.choice(brands)
        item_num = (pid % 50) + 1
        name = f"{brand} {subcat[:-1] if subcat.endswith('s') else subcat} Model {item_num}"
        unit_price = round(random.uniform(min_p, max_p), 2)
        # Cost price is 50% to 75% of unit price
        cost_price = round(unit_price * random.uniform(0.50, 0.75), 2)
        products.append((pid, name, cat, subcat, brand, unit_price, cost_price))
        pid += 1

    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", products)

    # 4. Seed Inventory (~2,500)
    inventory = []
    for p in range(1, num_products + 1):
        num_wh = random.randint(3, 7)
        chosen_warehouses = random.sample(range(1, 11), num_wh)
        for wid in chosen_warehouses:
            stock = random.randint(10, 500)
            restock = (datetime(2024, 1, 1) + timedelta(days=random.randint(0, 365))).strftime("%Y-%m-%d")
            inventory.append((p, wid, stock, restock))
    cursor.executemany("INSERT INTO inventory VALUES (?, ?, ?, ?)", inventory)

    # 5. Seed Orders (~50,000) & Order Items (~120,000) covering 2023 - 2025
    order_start = datetime(2023, 1, 1)
    order_days = (datetime(2025, 10, 1) - order_start).days
    statuses = ["delivered", "delivered", "delivered", "delivered", "shipped", "processing", "cancelled", "returned"]
    payment_methods = ["UPI", "Credit Card", "Debit Card", "Net Banking", "Cash on Delivery"]
    regions = ["West", "South", "North", "East"]
    discounts = [0.0, 0.0, 0.05, 0.10, 0.15, 0.20]

    num_orders = 50000
    orders = []
    order_items = []
    returns_list = []

    product_dict = {p[0]: p for p in products}  # pid -> tuple
    item_id_counter = 1
    return_id_counter = 1

    for oid in range(1, num_orders + 1):
        cid = random.randint(1, num_customers)
        # bias date towards 2024 for rich analytics
        random_day = random.randint(0, order_days)
        odt = order_start + timedelta(days=random_day)
        order_date = odt.strftime("%Y-%m-%d")
        status = random.choice(statuses)
        payment = random.choice(payment_methods)
        region = random.choice(regions)

        orders.append((oid, cid, order_date, status, payment, region))

        # 1 to 4 items per order
        num_items = random.choices([1, 2, 3, 4], weights=[45, 35, 15, 5])[0]
        chosen_pids = random.sample(range(1, num_products + 1), num_items)

        order_has_returned_items = (status == "returned")

        for pid in chosen_pids:
            prod = product_dict[pid]
            base_price = prod[5]  # unit_price
            qty = random.choices([1, 2, 3, 5], weights=[70, 20, 7, 3])[0]
            disc = random.choice(discounts)

            order_items.append((item_id_counter, oid, pid, qty, base_price, disc))

            # If order status is returned, or occasional return on delivered order
            is_return = order_has_returned_items or (status == "delivered" and random.random() < 0.04)
            if is_return:
                ret_dt = odt + timedelta(days=random.randint(1, 14))
                ret_date = ret_dt.strftime("%Y-%m-%d")
                reasons = ["Defective Item", "Wrong Size", "Not as Described", "Changed Mind", "Late Delivery"]
                reason = random.choice(reasons)
                refund_amt = round(qty * base_price * (1 - disc), 2)
                returns_list.append((return_id_counter, oid, pid, ret_date, reason, refund_amt))
                return_id_counter += 1

            item_id_counter += 1

    cursor.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", orders)
    cursor.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?)", order_items)
    cursor.executemany("INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?)", returns_list)

    # 6. Seed Marketing Campaigns (~20)
    campaigns = [
        (1, "New Year Kickoff 2023", "Google Ads", "2023-01-01", "2023-01-15", 150000.0),
        (2, "Republic Day Sale 2023", "Instagram", "2023-01-20", "2023-01-28", 250000.0),
        (3, "Holi Splash 2023", "YouTube", "2023-03-01", "2023-03-10", 180000.0),
        (4, "Summer Fest 2023", "Affiliate", "2023-05-01", "2023-05-31", 300000.0),
        (5, "Monsoon Bonanza 2023", "Email", "2023-07-10", "2023-07-25", 80000.0),
        (6, "Independence Day Mega Sale 2023", "Google Ads", "2023-08-08", "2023-08-16", 350000.0),
        (7, "Diwali Festive Dhamaka 2023", "Instagram", "2023-10-20", "2023-11-15", 750000.0),
        (8, "Black Friday Tech Fest 2023", "YouTube", "2023-11-24", "2023-11-30", 400000.0),
        (9, "Year End Clearance 2023", "Google Ads", "2023-12-20", "2023-12-31", 200000.0),
        (10, "New Year Carnival 2024", "Instagram", "2024-01-01", "2024-01-10", 220000.0),
        (11, "Republic Day Celebration 2024", "Google Ads", "2024-01-22", "2024-01-28", 280000.0),
        (12, "Valentine Gifts Gala 2024", "Instagram", "2024-02-07", "2024-02-14", 190000.0),
        (13, "Holi Colors Fest 2024", "YouTube", "2024-03-15", "2024-03-26", 210000.0),
        (14, "Summer Gadgets Expo 2024", "Google Ads", "2024-05-01", "2024-05-20", 380000.0),
        (15, "Freedom Sale 2024", "Instagram", "2024-08-10", "2024-08-18", 420000.0),
        (16, "Great Indian Festive Bash 2024", "YouTube", "2024-10-10", "2024-11-05", 900000.0),
        (17, "Cyber Week 2024", "Google Ads", "2024-11-28", "2024-12-05", 350000.0),
        (18, "Winter Warmup 2024", "Email", "2024-12-15", "2024-12-31", 120000.0),
        (19, "New Year Sparkle 2025", "Instagram", "2025-01-01", "2025-01-12", 260000.0),
        (20, "Spring Tech Launch 2025", "Google Ads", "2025-03-01", "2025-03-20", 310000.0),
    ]
    cursor.executemany("INSERT INTO marketing_campaigns VALUES (?, ?, ?, ?, ?, ?)", campaigns)

    # 7. Seed Employees (~50 with salary marked sensitive)
    roles = [
        ("Sales Manager", 85000, 140000),
        ("Support Specialist", 35000, 60000),
        ("Warehouse Associate", 25000, 45000),
        ("Data Analyst", 65000, 110000),
        ("Logistics Coordinator", 45000, 75000),
        ("Category Manager", 90000, 160000),
    ]
    employees = []
    for eid in range(1, 51):
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        emp_name = f"{fn} {ln}"
        role, min_sal, max_sal = random.choice(roles)
        reg = random.choice(regions)
        hdt = datetime(2021, 1, 1) + timedelta(days=random.randint(0, 1200))
        hire_date = hdt.strftime("%Y-%m-%d")
        salary = round(random.uniform(min_sal, max_sal), 2)
        employees.append((eid, emp_name, role, reg, hire_date, salary))

    cursor.executemany("INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?)", employees)

    conn.commit()


def main():
    db_path = os.getenv("DB_PATH", "data/retail.db")
    print(f"Creating database at {db_path}...")
    conn = create_connection(db_path)
    print("Creating tables and indexes...")
    create_tables(conn)
    print("Seeding data (customers, products, orders, items, returns, inventory, campaigns, employees)...")
    seed_data(conn)

    cursor = conn.cursor()
    print("\nDatabase seeded successfully! Row counts:")
    tables = [
        "customers", "products", "orders", "order_items", "returns",
        "warehouses", "inventory", "marketing_campaigns", "employees"
    ]
    for tbl in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
        count = cursor.fetchone()[0]
        print(f"  - {tbl:22s}: {count:,} rows")

    conn.close()


if __name__ == "__main__":
    main()
