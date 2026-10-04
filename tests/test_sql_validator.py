"""Unit tests for the read-only SQL validator security guardrails."""

import pytest
from querypilot.pipeline.sql_validator import SQLValidator


@pytest.fixture
def validator():
    return SQLValidator()


def test_valid_select_passes(validator):
    sql = "SELECT customer_id, name, city FROM customers WHERE state = 'Maharashtra' LIMIT 10"
    res = validator.validate(sql)
    assert res.is_valid is True
    assert len(res.errors) == 0
    assert "LIMIT 10" in res.sanitized_sql


def test_valid_join_without_limit_adds_default_limit(validator):
    sql = """
    SELECT o.order_id, o.order_date, c.name, p.name AS product_name
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    JOIN order_items oi ON o.order_id = oi.order_id
    JOIN products p ON oi.product_id = p.product_id
    WHERE o.status = 'delivered'
    """
    res = validator.validate(sql)
    assert res.is_valid is True
    assert "LIMIT 100" in res.sanitized_sql


def test_valid_cte_query(validator):
    sql = """
    WITH monthly_sales AS (
        SELECT strftime('%Y-%m', order_date) AS month, COUNT(*) AS total_orders
        FROM orders
        GROUP BY month
    )
    SELECT month, total_orders FROM monthly_sales ORDER BY month DESC
    """
    res = validator.validate(sql)
    assert res.is_valid is True
    assert "LIMIT 100" in res.sanitized_sql


def test_limit_capping_exceeding_max(validator):
    sql = "SELECT product_id, name, unit_price FROM products LIMIT 5000"
    res = validator.validate(sql)
    assert res.is_valid is True
    assert "LIMIT 1000" in res.sanitized_sql


@pytest.mark.parametrize(
    "malicious_sql, expected_error_substring",
    [
        ("DROP TABLE customers", "Drop"),
        ("DELETE FROM orders", "Delete"),
        ("INSERT INTO customers (customer_id, name) VALUES (999, 'Hacker')", "Insert"),
        ("UPDATE products SET unit_price = 0", "Update"),
        ("ALTER TABLE employees ADD COLUMN ssn TEXT", "Alter"),
        ("CREATE TABLE backdoor (id INT)", "Create"),
        ("SELECT 1; DROP TABLE customers;", "Multiple SQL statements"),
        ("SELECT 1; DELETE FROM orders WHERE 1=1;", "Multiple SQL statements"),
        ("ATTACH DATABASE 'malicious.db' AS mal", "Forbidden command detected"),
        ("DETACH DATABASE mal", "Forbidden command detected"),
        ("PRAGMA table_info(customers)", "Forbidden command detected"),
        ("PRAGMA query_only = OFF", "Forbidden command detected"),
        ("/* multiline comment */ DROP TABLE products;", "Drop"),
        ("-- single line comment \n DROP TABLE products;", "Drop"),
        ("SELECT name, salary FROM employees", "sensitive column"),
        ("SELECT email FROM customers", "sensitive column"),
        ("SELECT e.salary FROM employees e", "sensitive column"),
        ("SELECT * FROM employees", "Wildcard selection '*' is forbidden"),
        ("SELECT * FROM customers", "Wildcard selection '*' is forbidden"),
        ("SELECT * FROM (SELECT salary FROM employees)", "sensitive column"),
        ("SELECT name FROM customers UNION SELECT salary FROM employees", "sensitive column"),
        ("SELECT * FROM unknown_backdoor_table", "not in the allowed schema whitelist"),
        ("SELECT name FROM sqlite_master", "not in the allowed schema whitelist"),
        ("VACUUM", "Forbidden command detected"),
        ("SELECT load_extension('shell')", "Forbidden command detected"),
    ],
)
def test_malicious_and_write_queries_rejected(validator, malicious_sql, expected_error_substring):
    res = validator.validate(malicious_sql)
    assert res.is_valid is False
    assert any(expected_error_substring.lower() in err.lower() for err in res.errors)
