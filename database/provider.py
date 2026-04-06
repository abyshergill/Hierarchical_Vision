import aiosqlite
import os

DB_PATH = 'org_chart.sqlite'

def get_db():
    return aiosqlite.connect(DB_PATH)

async def init_db():
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        with open('database/init_db.sql', 'r') as f:
            schema = f.read()
        await db.executescript(schema)
        await db.commit()

async def get_employees(manager_id=None):
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT e.*, (SELECT COUNT(*) FROM employees WHERE manager_id = e.id) as report_count
            FROM employees e
            WHERE manager_id IS ?
        """
        async with db.execute(query, (manager_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_employee_by_id(employee_id):
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT e.*, (SELECT COUNT(*) FROM employees WHERE manager_id = e.id) as report_count
            FROM employees e
            WHERE id = ?
        """
        async with db.execute(query, (employee_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def search_employees(query):
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        search_query = f"%{query}%"
        sql = """
            SELECT e.*, (SELECT COUNT(*) FROM employees WHERE manager_id = e.id) as report_count
            FROM employees e
            WHERE name LIKE ? OR employee_id_str LIKE ?
        """
        async with db.execute(sql, (search_query, search_query)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_lineage(employee_id):
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        # Recursive CTE for lineage (Above)
        sql = """
            WITH RECURSIVE lineage AS (
                SELECT * FROM employees WHERE id = ?
                UNION ALL
                SELECT e.* FROM employees e
                INNER JOIN lineage l ON e.id = l.manager_id
            )
            SELECT * FROM lineage WHERE id != ?;
        """
        async with db.execute(sql, (employee_id, employee_id)) as cursor:
            rows = await cursor.fetchall()
            # Reverse to get top-down lineage
            return [dict(row) for row in reversed(rows)]

async def add_employee(data):
    async with get_db() as db:
        sql = """
            INSERT INTO employees (employee_id_str, name, email, contact, image_url, manager_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        cursor = await db.execute(sql, (
            data['employee_id_str'], data['name'], data['email'],
            data.get('contact'), data.get('image_url'), data.get('manager_id')
        ))
        await db.commit()
        return cursor.lastrowid

async def update_employee(employee_id, data):
    async with get_db() as db:
        sql = """
            UPDATE employees
            SET employee_id_str=?, name=?, email=?, contact=?, image_url=?, manager_id=?
            WHERE id=?
        """
        await db.execute(sql, (
            data['employee_id_str'], data['name'], data['email'],
            data.get('contact'), data.get('image_url'), data.get('manager_id'),
            employee_id
        ))
        await db.commit()

async def delete_employee(employee_id):
    async with get_db() as db:
        await db.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        await db.commit()
