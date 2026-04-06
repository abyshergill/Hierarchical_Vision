const canvasContent = document.getElementById('canvas-content');
const empModal = document.getElementById('emp-modal');
const empForm = document.getElementById('emp-form');

async function initCanvas() {
    canvasContent.innerHTML = '';
    const resp = await fetch('/api/employees?manager_id=null');
    const heads = await resp.json();
    
    heads.forEach(head => {
        const rootNode = createTreeNode(head, null);
        canvasContent.appendChild(rootNode);
    });
}

function createTreeNode(emp, branchIndex = null) {
    const node = document.createElement('div');
    node.className = 'tree-node';
    if (branchIndex !== null) {
        node.classList.add(`branch-${branchIndex % 6}`);
        node.dataset.branch = branchIndex;
    }
    node.id = `node-${emp.id}`;
    
    const card = createMemberCard(emp);
    node.appendChild(card);
    
    const subsContainer = document.createElement('div');
    subsContainer.className = 'subordinates-container';
    subsContainer.style.display = 'none';
    node.appendChild(subsContainer);
    
    // Expand toggle if has reports
    if (emp.report_count > 0) {
        const toggle = document.createElement('div');
        toggle.className = 'expand-toggle';
        toggle.innerHTML = `
            <svg viewBox="0 0 24 24">
                <path d="M6 9l6 6 6-6"></path>
            </svg>
        `;
        toggle.onclick = (e) => {
            e.stopPropagation();
            toggleSubordinates(emp.id, subsContainer, toggle, branchIndex);
        };
        card.appendChild(toggle);
    }
    
    return node;
}

function createMemberCard(emp) {
    const card = document.createElement('div');
    card.className = `member-card ${isAuthorized ? 'admin-active' : ''}`;
    
    card.innerHTML = `
        <div class="profile-pic">
            <img src="${emp.image_url || 'https://via.placeholder.com/150'}" alt="${emp.name}">
        </div>
        <div class="member-name">${emp.name}</div>
        <div class="member-id">${emp.employee_id_str}</div>
        <div class="member-info">${emp.email}</div>
        <div class="member-info">${emp.contact || 'No contact'}</div>
        ${emp.report_count > 0 ? `<div class="report-count">${emp.report_count}</div>` : ''}
        <div class="card-actions">
            <button class="btn btn-small btn-primary" onclick="showAddModal(${emp.id})">Add</button>
            <button class="btn btn-small" onclick="showEditModal(${JSON.stringify(emp).replace(/"/g, '&quot;')})">Edit</button>
            <button class="btn btn-small btn-danger" onclick="deleteEmp(${emp.id})">Delete</button>
        </div>
    `;
    
    return card;
}

async function toggleSubordinates(managerId, container, toggle, branchIndex) {
    if (container.style.display === 'none') {
        if (container.dataset.fetching === 'true') return;
        container.dataset.fetching = 'true';
        
        try {
            // ALWAYS clear to prevent duplication
            container.innerHTML = ''; 
            const resp = await fetch(`/api/employees/${managerId}/reports`);
            const reports = await resp.json();
            
            reports.forEach((report, idx) => {
                // If top-level reports (managerId is Head ID 1), assign new branch index
                // Otherwise inherit parent's branch index
                const currentBranch = (branchIndex === null) ? idx : branchIndex;
                container.appendChild(createTreeNode(report, currentBranch));
            });
            container.style.display = 'flex';
            toggle.classList.add('open');
        } finally {
            container.dataset.fetching = 'false';
        }
    } else {
        container.style.display = 'none';
        toggle.classList.remove('open');
    }
}

// CRUD Logic
function showAddModal(managerId) {
    document.getElementById('modal-title').textContent = 'Add Subordinate';
    document.getElementById('manager-id').value = managerId;
    document.getElementById('emp-id').value = '';
    empForm.reset();
    document.getElementById('form-image-url').value = ''; // Reset manually just in case
    empModal.style.display = 'block';
}

function showEditModal(emp) {
    document.getElementById('modal-title').textContent = 'Edit Member';
    document.getElementById('emp-id').value = emp.id;
    document.getElementById('manager-id').value = emp.manager_id || '';
    document.getElementById('form-emp-id-str').value = emp.employee_id_str;
    document.getElementById('form-name').value = emp.name;
    document.getElementById('form-email').value = emp.email;
    document.getElementById('form-contact').value = emp.contact || '';
    document.getElementById('form-image-url').value = emp.image_url || '';
    document.getElementById('form-image-file').value = ''; // Clear file input
    empModal.style.display = 'block';
}

async function deleteEmp(id) {
    if (!confirm('Are you sure you want to delete this employee and all their reports?')) return;
    const resp = await fetch(`/api/employees/${id}`, { method: 'DELETE' });
    if (resp.ok) initCanvas();
}

empForm.onsubmit = async (e) => {
    e.preventDefault();
    const id = document.getElementById('emp-id').value;
    let imageUrl = document.getElementById('form-image-url').value;
    const imageFile = document.getElementById('form-image-file').files[0];

    // Handle Upload
    if (imageFile) {
        const formData = new FormData();
        formData.append('file', imageFile);
        const uploadResp = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        const uploadData = await uploadResp.json();
        if (uploadData.url) imageUrl = uploadData.url;
    }

    const data = {
        employee_id_str: document.getElementById('form-emp-id-str').value,
        name: document.getElementById('form-name').value,
        email: document.getElementById('form-email').value,
        contact: document.getElementById('form-contact').value,
        image_url: imageUrl,
        manager_id: document.getElementById('manager-id').value || null
    };

    const method = id ? 'PUT' : 'POST';
    const url = id ? `/api/employees/${id}` : '/api/employees';
    
    const resp = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    
    if (resp.ok) {
        empModal.style.display = 'none';
        initCanvas();
    } else {
        const err = await resp.json();
        alert(err.error || 'Operation failed');
    }
};

document.getElementById('form-cancel').onclick = () => empModal.style.display = 'none';

// Initial load removed - now handled by index.html after auth check
// initCanvas();
