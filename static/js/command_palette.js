document.addEventListener('DOMContentLoaded', function() {
    // Inject Command Palette HTML
    const paletteHtml = `
    <div id="command-palette-overlay" class="cmd-overlay" style="display: none;" role="dialog" aria-modal="true" aria-label="命令面板 / Command Palette">
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
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    
    let isOpen = false;
    let selectedIndex = 0;
    let baseCommands = [];
    let remoteCommands = [];
    let filteredCommands = [];
    let debounceTimer = null;
    let remoteAbortController = null;

    // Icon Mapper
    function getIconForTitle(title, url) {
        if (!title) return '🔗';
        const t = title.toLowerCase();
        const u = (url || '').toLowerCase();
        
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
        if (t.includes('user') || t.includes('用户')) return '👤';
        if (t.includes('action') || t.includes('操作')) return '⚡';
        return '🔗';
    }

    // Collect Commands from DOM
    function collectCommands() {
        const commands = [];

        function collectLinkSet(selector, category, { requireVisible = false } = {}) {
            document.querySelectorAll(selector).forEach((link) => {
                if (requireVisible && link.offsetParent === null) {
                    return;
                }
                const title = (link.innerText || link.textContent || '').trim();
                const url = link.href;
                if (title && url && !url.includes('#') && !url.includes('javascript')) {
                    commands.push({
                        category,
                        title,
                        url,
                        icon: getIconForTitle(title, url)
                    });
                }
            });
        }

        collectLinkSet('.brand[href], nav[aria-label="Main Navigation"] a[href]', '导航 / Navigation', { requireVisible: true });
        collectLinkSet('#admin-menu a[href]', '管理 / Admin');
        collectLinkSet('#user-menu a[href]', '账户 / Account');
        collectLinkSet('#mobile-menu a[href]', '移动端 / Mobile');

        commands.push({ category: '系统 / System', title: '切换深色模式 / Toggle Dark Mode', action: toggleDarkMode, icon: '🌓' });
        commands.push({ category: '系统 / System', title: '刷新页面 / Reload Page', action: () => window.location.reload(), icon: '🔄' });

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
        const seenKeys = new Set();
        commands.forEach(cmd => {
            if (cmd.title && (cmd.title.includes('高级报表') || cmd.title.includes('Advanced Reports'))) {
                return;
            }

            const key = cmd.url || `${cmd.category}:${cmd.title}`;
            if (!seenKeys.has(key)) {
                seenKeys.add(key);
                uniqueCommands.push(cmd);
            }
        });

        baseCommands = uniqueCommands;
    }

    function applyTheme(theme) {
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('theme', theme);
        if (themeMeta) {
            themeMeta.setAttribute('content', theme === 'dark' ? '#0f172a' : '#4f46e5');
        }
    }

    function toggleDarkMode() {
        const currentTheme = document.documentElement.dataset.theme || 'light';
        applyTheme(currentTheme === 'dark' ? 'light' : 'dark');
    }
    
    // Remote Search
    async function fetchRemoteCommands(query) {
        if (!query || query.length < 2) {
            remoteCommands = [];
            return;
        }

        if (remoteAbortController) {
            remoteAbortController.abort();
        }
        const controller = new AbortController();
        remoteAbortController = controller;
        
        try {
            const response = await fetch(`/core/api/command-search/?q=${encodeURIComponent(query)}`, {
                signal: controller.signal,
                headers: { 'Accept': 'application/json' },
                cache: 'no-store'
            });
            if (response.ok) {
                const data = await response.json();
                remoteCommands = data.results || [];
                remoteCommands.forEach(cmd => {
                    if (!cmd.icon) cmd.icon = getIconForTitle(cmd.title, cmd.url);
                });
            } else {
                remoteCommands = [];
            }
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error('Command Search Error:', error);
            }
            remoteCommands = [];
        } finally {
            if (remoteAbortController === controller) {
                remoteAbortController = null;
            }
        }
    }

    // Functions
    function togglePalette() {
        isOpen = !isOpen;
        
        if (isOpen) {
            collectCommands(); // Refresh commands on open to respect current permissions/DOM state
            input.value = '';
            remoteCommands = [];
            filterCommands('');
            overlay.classList.add('open');
            overlay.style.display = 'flex';
            overlay.setAttribute('aria-hidden', 'false');
            input.focus();
            if (typeof window.setPageScrollLock === 'function') {
                window.setPageScrollLock(true);
            } else {
                document.body.classList.add('page-scroll-lock');
            }
        } else {
            closePalette();
        }
    }

    function closePalette() {
        if (!isOpen && overlay.style.display === 'none') {
            return;
        }
        isOpen = false;
        clearTimeout(debounceTimer);
        if (remoteAbortController) {
            remoteAbortController.abort();
            remoteAbortController = null;
        }
        overlay.classList.remove('open');
        overlay.style.display = 'none';
        overlay.setAttribute('aria-hidden', 'true');
        if (typeof window.setPageScrollLock === 'function') {
            window.setPageScrollLock(false);
        } else {
            document.body.classList.remove('page-scroll-lock');
        }
    }

    async function filterCommands(query) {
        const q = query.toLowerCase();
        
        // Local Filter
        let localFiltered = baseCommands.filter(cmd => 
            cmd.title.toLowerCase().includes(q) || 
            cmd.category.toLowerCase().includes(q)
        );
        
        if (q.length < 2) {
            remoteCommands = [];
        }

        filteredCommands = [...remoteCommands, ...localFiltered];
        
        // Remove duplicates again if remote returns same as local (unlikely but possible for navigation)
        const seen = new Set();
        filteredCommands = filteredCommands.filter(cmd => {
            const key = cmd.url || cmd.title;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });

        if (q.length < 2) {
            filteredCommands.sort((a, b) => {
                if (a.category < b.category) return -1;
                if (a.category > b.category) return 1;
                return a.title.localeCompare(b.title);
            });
        }

        selectedIndex = 0;
        renderList();
    }

    function renderList() {
        list.replaceChildren();
        
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

            const icon = document.createElement('span');
            icon.className = 'cmd-item-icon';
            icon.textContent = cmd.icon || '🔗';

            const title = document.createElement('span');
            title.className = 'cmd-item-title';
            title.textContent = cmd.title;

            item.appendChild(icon);
            item.appendChild(title);

            if (index === selectedIndex) {
                const enterHint = document.createElement('span');
                enterHint.className = 'cmd-enter-hint';
                enterHint.textContent = '↵';
                item.appendChild(enterHint);
            }
            
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
                    const enterHint = document.createElement('span');
                    enterHint.className = 'cmd-enter-hint';
                    enterHint.textContent = '↵';
                    item.appendChild(enterHint);
                }
            });
            
            list.appendChild(item);
        });
        
        scrollToSelected();
    }

    function renderSelectionOnly() {
        const items = list.querySelectorAll('.cmd-item');
        if (!items.length) {
            return;
        }
        items.forEach((item, index) => {
            if (index === selectedIndex) {
                item.classList.add('selected');
                if (!item.querySelector('.cmd-enter-hint')) {
                    const enterHint = document.createElement('span');
                    enterHint.className = 'cmd-enter-hint';
                    enterHint.textContent = '↵';
                    item.appendChild(enterHint);
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
            if (!filteredCommands.length) return;
            e.preventDefault();
            selectedIndex = (selectedIndex + 1) % filteredCommands.length;
            renderSelectionOnly();
        } else if (e.key === 'ArrowUp') {
            if (!filteredCommands.length) return;
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
        const query = e.target.value.trim();
        
        // Local filter is immediate
        filterCommands(query);
        
        // Remote filter is debounced
        clearTimeout(debounceTimer);
        if (query.length >= 2) {
            debounceTimer = setTimeout(async () => {
                await fetchRemoteCommands(query);
                filterCommands(query); // Re-filter to merge remote results
            }, 300);
        }
    });

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            closePalette();
        }
    });

    overlay.setAttribute('aria-hidden', 'true');
});
