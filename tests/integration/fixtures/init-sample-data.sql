-- Sample data initialization script for integration tests
-- This creates tables and data that will be used by Metabase questions

-- Create schema
CREATE SCHEMA IF NOT EXISTS public;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Products table
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    category VARCHAR(100),
    stock_quantity INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending'
);

-- Order items table
CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL
);

-- Insert sample users
INSERT INTO users (username, email, is_active) VALUES
    ('john_doe', 'john@example.com', TRUE),
    ('jane_smith', 'jane@example.com', TRUE),
    ('bob_wilson', 'bob@example.com', TRUE),
    ('alice_brown', 'alice@example.com', FALSE),
    ('charlie_davis', 'charlie@example.com', TRUE)
ON CONFLICT (username) DO NOTHING;

-- Insert sample products
INSERT INTO products (name, description, price, category, stock_quantity) VALUES
    ('Laptop', 'High-performance laptop', 1299.99, 'Electronics', 50),
    ('Mouse', 'Wireless mouse', 29.99, 'Electronics', 200),
    ('Keyboard', 'Mechanical keyboard', 89.99, 'Electronics', 150),
    ('Monitor', '27-inch 4K monitor', 399.99, 'Electronics', 75),
    ('Desk Chair', 'Ergonomic office chair', 249.99, 'Furniture', 30),
    ('Desk', 'Standing desk', 499.99, 'Furniture', 20),
    ('Notebook', 'Spiral notebook', 4.99, 'Stationery', 500),
    ('Pen Set', 'Premium pen set', 19.99, 'Stationery', 300),
    ('Headphones', 'Noise-cancelling headphones', 199.99, 'Electronics', 100),
    ('Webcam', 'HD webcam', 79.99, 'Electronics', 80)
ON CONFLICT DO NOTHING;

-- Insert sample orders
INSERT INTO orders (user_id, order_date, total_amount, status) VALUES
    (1, '2025-01-15 10:30:00', 1329.98, 'completed'),
    (2, '2025-01-16 14:20:00', 89.99, 'completed'),
    (1, '2025-01-17 09:15:00', 649.98, 'shipped'),
    (3, '2025-01-18 16:45:00', 279.98, 'pending'),
    (5, '2025-01-19 11:00:00', 1799.97, 'completed'),
    (2, '2025-01-20 13:30:00', 24.98, 'completed'),
    (1, '2025-01-21 10:00:00', 499.99, 'processing'),
    (3, '2025-01-22 15:20:00', 199.99, 'shipped'),
    (5, '2025-01-23 12:10:00', 109.98, 'completed'),
    (2, '2025-01-24 14:50:00', 399.99, 'pending')
ON CONFLICT DO NOTHING;

-- Insert sample order items
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 1, 1299.99),
    (1, 2, 1, 29.99),
    (2, 3, 1, 89.99),
    (3, 4, 1, 399.99),
    (3, 5, 1, 249.99),
    (4, 9, 1, 199.99),
    (4, 2, 1, 29.99),
    (4, 8, 2, 19.99),
    (5, 1, 1, 1299.99),
    (5, 6, 1, 499.99),
    (6, 7, 5, 4.99),
    (7, 6, 1, 499.99),
    (8, 9, 1, 199.99),
    (9, 3, 1, 89.99),
    (9, 8, 1, 19.99),
    (10, 4, 1, 399.99)
ON CONFLICT DO NOTHING;

-- Create some views for testing
CREATE OR REPLACE VIEW user_order_summary AS
SELECT 
    u.id,
    u.username,
    u.email,
    COUNT(o.id) as total_orders,
    COALESCE(SUM(o.total_amount), 0) as total_spent
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.username, u.email;

CREATE OR REPLACE VIEW product_sales_summary AS
SELECT 
    p.id,
    p.name,
    p.category,
    p.price,
    COALESCE(SUM(oi.quantity), 0) as total_sold,
    COALESCE(SUM(oi.quantity * oi.unit_price), 0) as total_revenue
FROM products p
LEFT JOIN order_items oi ON p.id = oi.product_id
GROUP BY p.id, p.name, p.category, p.price;

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sample_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sample_user;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO sample_user;

