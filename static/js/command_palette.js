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
    
    if (!document.getElementById('command-palette-overlay')) {
        document.body.insertAdjacentHTML('beforeend', paletteHtml);
    }

    // State
    const overlay = document.getElementById('command-palette-overlay');
    const input = document.getElementById('cmd-input');
    const list = document.getElementById('cmd-list');
    const emptyState = document.getElementById('cmd-empty');
    
    let isOpen = false;
    let selectedIndex = 0;
    let baseCommands = [];
    let filteredCommands = [];

    // Icon Mapper
    function getIconForTitle(title, url) {
        const t = title.toLowerCase();
        const u = url.toLowerCase();
        if (t.includes('work') || t.includes('工作台')) return '🏠';
        if (t.includes('project') || t.includes('项目')) return '📂';
        if (t.includes('task') || t.includes('任务')) return '✅';
        if (t.includes('report') || t.includes('日报')) return '📄';
        if (t.includes('admin') || t.includes('管理')) return '🔧';
        if (t.includes('setting') || t.includes('设置') || t.includes('center') || t.includes('中心')) return '⚙️';
        if (t.includes('logout') || t.includes('退出')) return '🚪';
        if (t.includes('search') || t.includes('搜索')) return '🔍';
        if (t.includes('team') || t.includes('团队')) return '👥';
        if (t.includes('stats') || t.includes('统计') || t.includes('board') || t.includes('看板')) return '📊';
        if (t.includes('template') || t.includes('模板')) return '📋';
        if (t.includes('audit') || t.includes('审计')) return '🛡️';
        return '🔗';
    }

    // Collect Commands from DOM
    function collectCommands() {
        const commands = [];
        
        // 1. Topbar Links (Main Navigation)
        const navLinks = document.querySelectorAll('.topbar a:not(.admin-menu a)');
        navLinks.forEach(link => {
            if (link.offsetParent === null) return; // Skip hidden
            const title = link.innerText.trim();
            const url = link.href;
            if (title && url && !url.includes('#') && !url.includes('javascript')) {
                commands.push({
                    category: '导航 / Navigation',
                    title: title,
                    url: url,
                    icon: getIconForTitle(title, url)
                });
            }
        });

        // 2. Admin Menu Links
        const adminLinks = document.querySelectorAll('.admin-menu a');
        adminLinks.forEach(link => {
            const title = link.innerText.trim();
            const url = link.href;
            if (title && url) {
                commands.push({
                    category: '管理 / Admin',
                    title: title,
                    url: url,
                    icon: getIconForTitle(title, url)
                });
            }
        });

        // 3. System / Actions
        commands.push({ category: '系统 / System', title: '切换深色模式 / Toggle Dark Mode', action: toggleDarkMode, icon: '🌓' });
        commands.push({ category: '系统 / System', title: '刷新页面 / Reload Page', action: () => window.location.reload(), icon: '🔄' });
        
        // 4. Logout (Special case if not found in links)
        const logoutForm = document.getElementById('logout-form');
        if (logoutForm) {
             commands.push({ 
                 category: '账户 / Account', 
                 title: '退出登录 / Logout', 
                 action: () => logoutForm.submit(), 
                 icon: '🚪' 
             });
        }

        // Deduplicate by URL
        const uniqueCommands = [];
        const seenUrls = new Set();
        commands.forEach(cmd => {
            // Remove 'Advanced Reports' / '高级报表'
            if (cmd.title && (cmd.title.includes('高级报表') || cmd.title.includes('Advanced Reports'))) {
                return;
            }

            if (cmd.url) {
                if (!seenUrls.has(cmd.url)) {
                    seenUrls.add(cmd.url);
                    uniqueCommands.push(cmd);
                }
            } else {
                uniqueCommands.push(cmd); // Actions always added
            }
        });

        baseCommands = uniqueCommands;
    }

    function toggleDarkMode() {
        // Simple mock implementation or hook into existing theme logic
        document.documentElement.classList.toggle('dark');
        alert('Dark mode toggled (implementation depends on CSS)');
    }

    // Functions
    function togglePalette() {
        isOpen = !isOpen;
        
        if (isOpen) {
            collectCommands(); // Refresh commands on open to respect current permissions/DOM state
            input.value = '';
            filterCommands('');
            overlay.style.display = 'flex';
            input.focus();
            document.body.style.overflow = 'hidden';
        } else {
            overlay.style.display = 'none';
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
        
        // Sort: Category > Title
        filteredCommands.sort((a, b) => {
            if (a.category < b.category) return -1;
            if (a.category > b.category) return 1;
            return a.title.localeCompare(b.title);
        });

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
                executeCommand(cmd);
            });
            
            item.addEventListener('mouseenter', () => {
                // Update selection visually but don't auto-scroll
                const prev = list.querySelector('.cmd-item.selected');
                if (prev) {
                    prev.classList.remove('selected');
                    const hint = prev.querySelector('.cmd-enter-hint');
                    if (hint) hint.remove();
                }
                
                selectedIndex = index;
                item.classList.add('selected');
                if (!item.querySelector('.cmd-enter-hint')) {
                   item.insertAdjacentHTML('beforeend', '<span class="cmd-enter-hint">↵</span>');
                }
            });
            
            list.appendChild(item);
        });
        
        scrollToSelected();
    }

    function renderSelectionOnly() {
        // Re-implementing correctly to handle the category headers which disrupt index mapping
        // Actually, renderList is fast enough for < 100 items. 
        // But for "Arrow" navigation, we want to update classes.
        // The issue is `list.children` includes category headers, so index doesn't match `filteredCommands`.
        // Better to query only .cmd-item
        const items = list.querySelectorAll('.cmd-item');
        items.forEach((item, index) => {
            if (index === selectedIndex) {
                item.classList.add('selected');
                if (!item.querySelector('.cmd-enter-hint')) {
                   item.insertAdjacentHTML('beforeend', '<span class="cmd-enter-hint">↵</span>');
                }
                item.scrollIntoView({ block: 'nearest' });
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

    function executeCommand(cmd) {
        closePalette();
        if (cmd.action) {
            cmd.action();
        } else if (cmd.url) {
            window.location.href = cmd.url;
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
            e.preventDefault();
            closePalette();
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            selectedIndex = (selectedIndex + 1) % filteredCommands.length;
            renderSelectionOnly();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIndex = (selectedIndex - 1 + filteredCommands.length) % filteredCommands.length;
            renderSelectionOnly();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (filteredCommands[selectedIndex]) {
                executeCommand(filteredCommands[selectedIndex]);
            }
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