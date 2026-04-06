-- Create employees table
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id_str TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    contact TEXT,
    image_url TEXT,
    manager_id INTEGER,
    FOREIGN KEY (manager_id) REFERENCES employees(id) ON DELETE SET NULL
);

-- Seed data: Tier 1 (The Head)
INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id) 
VALUES ('EMP-100', 'Arthur "Apple" Head', 'arthur@apple-org.com', '+1-555-0100', '/static/assets/p1.png', NULL);

-- Seed data: Tier 2 (Direct Reports to Head)
INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id) 
VALUES ('EMP-101', 'Beatrice Branch', 'beatrice@apple-org.com', '+1-555-0101', '/static/assets/p2.png', 1);
INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id) 
VALUES ('EMP-102', 'Charlie Canopy', 'charlie@apple-org.com', '+1-555-0102', '/static/assets/p3.png', 1);
INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id) 
VALUES ('EMP-103', 'Diana Dew', 'diana@apple-org.com', '+1-555-0103', '/static/assets/p4.png', 1);

-- Seed data: Tier 3 (Reports to Tier 2)
INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id) 
VALUES ('EMP-104', 'Edward Edge', 'edward@apple-org.com', '+1-555-0104', '/static/assets/p5.png', 2);
INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id) 
VALUES ('EMP-105', 'Fiona Fern', 'fiona@apple-org.com', '+1-555-0105', '/static/assets/p6.png', 2);
INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id) 
VALUES ('EMP-106', 'George Grove', 'george@apple-org.com', '+1-555-0106', '/static/assets/p7.png', 3);
INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id) 
VALUES ('EMP-107', 'Hannah Hill', 'hannah@apple-org.com', '+1-555-0107', '/static/assets/p8.png', 4);
INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id) 
VALUES ('EMP-108', 'Ian Island', 'ian@apple-org.com', '+1-555-0108', '/static/assets/p9.png', 4);
