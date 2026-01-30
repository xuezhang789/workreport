document.addEventListener('DOMContentLoaded', function() {
    // Inject Command Palette HTML
    const paletteHtml = `
    <div id="command-palette-overlay" class="cmd-overlay" style="display: none;">
        <div class="cmd-modal">
            <div class="cmd-header">
                <div class="cmd-search-icon">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M19 19L14.65 14.65M17 9C17 13.4183 13.4183 17 9 17C4.58172 17 1 13.4183 1 9C1 4.58172 4.58172 1 9 1C13.4183 1 17 4.58172 17 9Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </div>
                <input type="text" id="cmd-input" class="cmd-input" placeholder="Search commands..." autocomplete="off">
                <div class="cmd-esc">Esc</div>
            </div>
            <div class="cmd-body">
                <div id="cmd-list" class="cmd-list">
                    <!-- Commands will be injected here -->
                </div>
                <div id="cmd-empty" class="cmd-empty" style="display: none;">
                    No results found.
                </div>
            </div>
            <div class="cmd-footer">
                <div class="cmd-shortcut-hint">
                    <span>↑↓</span> to navigate
                </div>
                <div class="cmd-shortcut-hint">
                    <span>↵</span> to select
                </div>
            </div>
        </div>
    </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', paletteHtml);

    // State
    const overlay = document.getElementById('command-palette-overlay');
    const input = document.getElementById('cmd-input');
    const list = document.getElementById('cmd-list');
    const emptyState = document.getElementById('cmd-empty');
    
    let isOpen = false;
    let selectedIndex = 0;
    let filteredCommands = [];

    // Define Commands
    // We can grab some from the DOM or define static ones. 
    // Static ensures they work even if not currently visible in nav.
    const baseCommands = [
        { category: '导航 / Navigation', title: '个人工作台 / Personal Workbench', url: '/reports/workbench/', icon: '🏠' },
        { category: '导航 / Navigation', title: '我的日报 / My Reports', url: '/reports/my/', icon: '📄' },
        { category: '导航 / Navigation', title: '新建日报 / Create Daily Report', url: '/reports/new/', icon: '✏️' },
        { category: '导航 / Navigation', title: '我的任务 / My Tasks', url: '/reports/tasks/', icon: '✅' },
        { category: '导航 / Navigation', title: '项目列表 / Projects List', url: '/reports/projects/', icon: '📂' },
        { category: '导航 / Navigation', title: '账户设置 / Account Settings', url: '/account/settings/', icon: '⚙️' },
        
        // Admin - only if links exist or we just show them (server will handle 403 if clicked)
        // Better to check if they exist in DOM or just include them as "System"
        { category: '管理 / Admin', title: '团队管理 / Team Management', url: '/reports/teams/', icon: '👥' },
        { category: '管理 / Admin', title: '管理员日报 / Admin Reports', url: '/reports/admin/reports/', icon: '📊' },
        { category: '管理 / Admin', title: '任务管理 / Task Administration', url: '/reports/tasks/admin/', icon: '🔧' },
        { category: '管理 / Admin', title: '绩效看板 / Performance Board', url: '/reports/performance/', icon: '📈' },
        { category: '管理 / Admin', title: '高级报表 / Advanced Reports', url: '/reports/advanced/', icon: '🚀' },
        { category: '管理 / Admin', title: '模板中心 / Template Center', url: '/reports/templates/center/', icon: '📋' },
        { category: '管理 / Admin', title: '审计日志 / Audit Logs', url: '/reports/audit/', icon: '🛡️' },
    ];

    // Functions
    function togglePalette() {
        isOpen = !isOpen;
        overlay.style.display = isOpen ? 'flex' : 'none';
        
        if (isOpen) {
            input.value = '';
            filterCommands('');
            input.focus();
            document.body.style.overflow = 'hidden'; // Prevent background scrolling
        } else {
            document.body.style.overflow = '';
        }
    }

    function closePalette() {
        isOpen = false;
        overlay.style.display = 'none';
        document.body.style.overflow = '';
    }

    function filterCommands(query) {
        const q = query.toLowerCase();
        filteredCommands = baseCommands.filter(cmd => 
            cmd.title.toLowerCase().includes(q) || 
            cmd.category.toLowerCase().includes(q)
        );
        
        selectedIndex = 0;
        renderList();
    }

    function renderList() {
        list.innerHTML = '';
        
        if (filteredCommands.length === 0) {
            emptyState.style.display = 'block';
            return;
        }
        
        emptyState.style.display = 'none';
        
        let lastCategory = '';
        
        filteredCommands.forEach((cmd, index) => {
            // Add Category Header if needed
            if (cmd.category !== lastCategory) {
                const catHeader = document.createElement('div');
                catHeader.className = 'cmd-category';
                catHeader.textContent = cmd.category;
                list.appendChild(catHeader);
                lastCategory = cmd.category;
            }
            
            const item = document.createElement('div');
            item.className = `cmd-item ${index === selectedIndex ? 'selected' : ''}`;
            item.innerHTML = `
                <span class="cmd-item-icon">${cmd.icon}</span>
                <span class="cmd-item-title">${cmd.title}</span>
                ${index === selectedIndex ? '<span class="cmd-enter-hint">↵</span>' : ''}
            `;
            
            item.addEventListener('click', () => {
                window.location.href = cmd.url;
                closePalette();
            });
            
            item.addEventListener('mouseenter', () => {
                selectedIndex = index;
                renderSelectionOnly(); // Optimization: don't re-render whole list
            });
            
            list.appendChild(item);
        });
        
        scrollToSelected();
    }

    function renderSelectionOnly() {
        const items = list.querySelectorAll('.cmd-item');
        items.forEach((item, index) => {
            if (index === selectedIndex) {
                item.classList.add('selected');
                if (!item.querySelector('.cmd-enter-hint')) {
                   item.insertAdjacentHTML('beforeend', '<span class="cmd-enter-hint">↵</span>');
                }
            } else {
                item.classList.remove('selected');
                const hint = item.querySelector('.cmd-enter-hint');
                if (hint) hint.remove();
            }
        });
    }

    function scrollToSelected() {
        const items = list.querySelectorAll('.cmd-item');
        if (items[selectedIndex]) {
            items[selectedIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    function executeSelected() {
        if (filteredCommands[selectedIndex]) {
            window.location.href = filteredCommands[selectedIndex].url;
            closePalette();
        }
    }

    // Event Listeners
    document.addEventListener('keydown', function(e) {
        // Toggle: Cmd+K or Ctrl+K
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            togglePalette();
        }
        
        if (!isOpen) return;

        if (e.key === 'Escape') {
            closePalette();
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            selectedIndex = (selectedIndex + 1) % filteredCommands.length;
            renderSelectionOnly();
            scrollToSelected();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIndex = (selectedIndex - 1 + filteredCommands.length) % filteredCommands.length;
            renderSelectionOnly();
            scrollToSelected();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            executeSelected();
        }
    });

    input.addEventListener('input', (e) => {
        filterCommands(e.target.value);
    });

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            closePalette();
        }
    });
});
