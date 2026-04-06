import asyncio
import os
import database.provider as db

async def test_hierarchy():
    # 1. Initialize DB
    if os.path.exists('org_chart.sqlite'):
        os.remove('org_chart.sqlite')
    await db.init_db()
    
    # 2. Test Get Head
    heads = await db.get_employees(None)
    print(f"Found {len(heads)} heads. First: {heads[0]['name']}")
    assert len(heads) == 1
    assert heads[0]['employee_id_str'] == 'EMP-100'
    
    # 3. Test Direct Reports for Head (EMP-100, ID 1)
    reports = await db.get_employees(1)
    print(f"EMP-100 has {len(reports)} direct reports.")
    assert len(reports) == 3 # EMP-101, 102, 103
    
    # 4. Test Search Fiona Fern
    results = await db.search_employees('Fiona')
    print(f"Search 'Fiona' returned {len(results)} results.")
    assert len(results) == 1
    fiona = results[0]
    print(f"Fiona has {fiona['report_count']} reports.")
    
    # 5. Test Lineage for Fiona (ID 6)
    # Fiona -> Beatrice (2) -> Arthur (1)
    lineage = await db.get_lineage(6)
    print(f"Fiona's lineage: {[e['name'] for e in lineage]}")
    assert len(lineage) == 2
    assert lineage[0]['id'] == 1 # Arthur
    assert lineage[1]['id'] == 2 # Beatrice

    print("--- ALL TESTS PASSED ---")

if __name__ == "__main__":
    asyncio.run(test_hierarchy())
