const searchInput = document.getElementById('search-input');
const searchOverlay = document.getElementById('search-overlay');
const closeSearch = document.getElementById('close-search');
const resultsGrid = document.getElementById('results-grid');
const lineageChain = document.getElementById('lineage-chain');

let searchTimeout;

searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(performSearch, 300);
});

closeSearch.onclick = () => {
    searchOverlay.style.display = 'none';
    searchInput.value = '';
};

async function performSearch() {
    const query = searchInput.value.trim();
    if (query.length < 1) {
        searchOverlay.style.display = 'none';
        return;
    }

    const resp = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    const data = await resp.json();
    
    renderSearchResults(data);
    searchOverlay.style.display = 'flex';
}

function renderSearchResults(data) {
    resultsGrid.innerHTML = '';
    lineageChain.innerHTML = '';

    // Render Results
    data.results.forEach(emp => {
        const card = createMemberCard(emp);
        card.onclick = async () => {
            // Drill down from search
            // This would require fetching the full path to this employee
            // For now, let's just show their immediate reports
            searchOverlay.style.display = 'none';
            searchInput.value = '';
            // Update path (complex to reconstruct full lineage without recursive API call)
            // But we can just jump to them
            currentPath = []; // Clear for now
            await loadHierarchy(emp.id);
        };
        resultsGrid.appendChild(card);
    });

    // Render Lineage
    if (data.lineage && data.lineage.length > 0) {
        document.getElementById('lineage-container').style.display = 'block';
        data.lineage.forEach(emp => {
            const item = document.createElement('div');
            item.className = 'lineage-item';
            item.innerHTML = `<strong>${emp.name}</strong> (${emp.employee_id_str})`;
            lineageChain.appendChild(item);
        });
    } else {
        document.getElementById('lineage-container').style.display = 'none';
    }
}
