import asyncio
import os
import database.provider as db

async def test_crud():
    # 1. Add employee
    new_emp = {
        'employee_id_str': 'EMP-999',
        'name': 'Test User',
        'email': 'test@apple-org.com',
        'contact': '12345',
        'image_url': None,
        'manager_id': 1
    }
    new_id = await db.add_employee(new_emp)
    print(f"Added employee with ID: {new_id}")
    
    # 2. Verify
    emp = await db.get_employee_by_id(new_id)
    assert emp['name'] == 'Test User'
    
    # 3. Update
    new_emp['name'] = 'Updated User'
    await db.update_employee(new_id, new_emp)
    emp = await db.get_employee_by_id(new_id)
    assert emp['name'] == 'Updated User'
    
    # 4. Delete
    await db.delete_employee(new_id)
    emp = await db.get_employee_by_id(new_id)
    assert emp is None
    print("CRUD tests passed.")

if __name__ == "__main__":
    asyncio.run(test_crud())
