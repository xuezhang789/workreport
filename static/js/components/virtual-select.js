
class VirtualProjectSelect {
    constructor(options = {}) {
        this.input = document.getElementById(options.inputId || 'vs-input');
        this.hidden = document.getElementById(options.hiddenId || 'vs-hidden');
        this.dropdown = document.getElementById(options.dropdownId || 'vs-dropdown');
        this.listContainer = document.getElementById(options.listContainerId || 'vs-list-container');
        this.loading = document.getElementById(options.loadingId || 'vs-loading');
        this.empty = document.getElementById(options.emptyId || 'vs-empty');
        
        this.indicator = document.getElementById(options.indicatorId || 'vs-indicator');
        this.debugMsg = document.getElementById(options.debugMsgId || 'vs-debug-msg');
        
        this.api = options.api || '';
        this.scope = options.scope || 'my_involved';
        
        this.allProjects = []; // Local cache
        this.filteredProjects = [];
        
        this.highlightIndex = -1;
        this.searchDebounce = null;
        this.isOpen = false;
        
        if (this.input) {
            // Ensure dropdown is hidden initially
            this.dropdown.style.display = 'none';
            this.init();
        }
    }

    async init() {
        // Remove initial style.maxHeight, let JS handle it dynamically
        this.dropdown.style.maxHeight = ''; 
        
        // Append dropdown to body to avoid clipping/overflow issues in parents
        if (this.dropdown.parentElement !== document.body) {
            document.body.appendChild(this.dropdown);
        }

        // Event Listeners
        this.input.addEventListener('focus', () => this.onFocus());
        // Delay blur to allow click on item
        this.input.addEventListener('blur', () => setTimeout(() => this.close(), 250));
        this.input.addEventListener('input', (e) => this.onInput(e.target.value));
        this.input.addEventListener('keydown', (e) => this.onKeydown(e));
        this.input.addEventListener('click', () => {
            if (!this.isOpen) this.onFocus();
        });
        
        // Reposition on scroll/resize
        window.addEventListener('scroll', () => { if (this.isOpen) this.reposition(); }, {passive: true});
        window.addEventListener('resize', () => { if (this.isOpen) this.reposition(); }, {passive: true});
        
        // Fetch Data (Lite Mode)
        this.setLoading(true);
        this.updateDebug("正在加载项目数据... / Loading projects...");
        
        try {
            // Fetch projects for client-side search (Lite Mode)
            const ts = new Date().getTime();
            const res = await fetch(`${this.api}?mode=lite&limit=5000&scope=${this.scope}&_t=${ts}`);
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            const data = await res.json();
            this.allProjects = data.results || [];
            
            // Sort by ID desc (recent first)
            this.allProjects.sort((a, b) => b.id - a.id);
            
            // Debug logging
            console.log(`[VirtualSelect] Loaded ${this.allProjects.length} projects`);
            this.updateDebug(`已加载 ${this.allProjects.length} 个项目 (仅限负责/参与) / Loaded ${this.allProjects.length} projects (My Involved)`);
            
            this.filteredProjects = this.allProjects;
            this.setLoading(false);
            
            if (this.allProjects.length === 0) {
                 this.empty.innerHTML = '<span>未找到任何项目 (No projects found)</span><br><small style="color:#cbd5e1">请确认已被分配项目</small>';
                 this.empty.style.display = 'block';
                 this.updateDebug("⚠️ 未找到任何项目，请联系管理员分配项目 / No projects found");
            } else {
                 this.empty.style.display = 'none';
            }
            
            // Initial render (limited)
            this.renderList();
            
            // Restore initial value if present
            if (this.hidden.value) {
                 const initialId = parseInt(this.hidden.value);
                 const p = this.allProjects.find(x => x.id === initialId);
                 if (p) {
                     this.input.value = `${p.name} [${p.code}]`;
                 }
            }
        } catch (e) {
            console.error('Failed to load projects', e);
            this.updateDebug(`❌ 加载失败 / Load failed: ${e.message}`);
            this.loading.innerHTML = '加载失败 / Load failed <button type="button" class="btn btn-sm btn-ghost" onclick="window.virtualProjectSelect.init()">重试 / Retry</button>';
        }
    }
    
    updateDebug(msg) {
        if (this.debugMsg) {
            this.debugMsg.textContent = msg;
            this.debugMsg.style.display = 'block';
        }
    }
    
    setLoading(isLoading) {
        if (isLoading) {
            this.loading.style.display = 'block';
            this.listContainer.style.display = 'none';
            if (this.indicator) this.indicator.textContent = '...';
        } else {
            this.loading.style.display = 'none';
            this.listContainer.style.display = 'block';
            if (this.indicator) this.indicator.textContent = '▼';
        }
    }

    onFocus() {
        this.isOpen = true;
        this.dropdown.classList.add('open');
        this.dropdown.style.display = 'block';
        this.reposition();
        
        if (!this.input.value.trim() || this.input.value.includes('[')) {
            // If empty or already selected, reset to full list (limited)
            this.filteredProjects = this.allProjects;
            this.renderList();
        } else {
            this.filter(this.input.value);
        }
    }

    close() {
        this.isOpen = false;
        this.dropdown.classList.remove('open');
        this.dropdown.style.display = 'none';
    }

    reposition() {
        if (!this.isOpen) return;
        const rect = this.input.getBoundingClientRect();
        
        if (rect.width === 0 || rect.height === 0) {
            this.close();
            return;
        }
        
        // Standard Absolute Positioning relative to Document Body
        this.dropdown.style.position = 'absolute';
        this.dropdown.style.top = `${rect.bottom + window.scrollY + 4}px`;
        this.dropdown.style.left = `${rect.left + window.scrollX}px`;
        this.dropdown.style.width = `${rect.width}px`;
        this.dropdown.style.zIndex = '9999';
        
        // Allow full expansion downwards
        this.dropdown.style.maxHeight = 'none';
        this.dropdown.style.height = 'auto';
        this.listContainer.style.maxHeight = 'none';
        this.listContainer.style.height = 'auto';
        this.dropdown.classList.remove('flipped');
    }

    onInput(q) {
        clearTimeout(this.searchDebounce);
        this.searchDebounce = setTimeout(() => {
            this.filter(q);
        }, 200);
    }

    filter(q) {
        if (!q || q.length < 1) { 
            this.filteredProjects = this.allProjects;
        } else {
            const lowerQ = q.toLowerCase();
            this.filteredProjects = this.allProjects.filter(p => 
                (p.name && p.name.toLowerCase().includes(lowerQ)) || 
                (p.code && p.code.toLowerCase().includes(lowerQ)) ||
                (p.pinyin && p.pinyin.toLowerCase().includes(lowerQ)) ||
                String(p.id) === lowerQ
            );
            
            this.filteredProjects.sort((a, b) => {
                 const aExact = (a.code && a.code.toLowerCase() === lowerQ) || (a.name && a.name.toLowerCase() === lowerQ);
                 const bExact = (b.code && b.code.toLowerCase() === lowerQ) || (b.name && b.name.toLowerCase() === lowerQ);
                 if (aExact && !bExact) return -1;
                 if (!aExact && bExact) return 1;
                 
                 const aStart = a.code && a.code.toLowerCase().startsWith(lowerQ);
                 const bStart = b.code && b.code.toLowerCase().startsWith(lowerQ);
                 if (aStart && !bStart) return -1;
                 if (!aStart && bStart) return 1;
                 
                 return 0; 
            });
        }
        
        this.highlightIndex = -1;
        this.renderList();
        
        if (this.filteredProjects.length === 0) {
            this.empty.style.display = 'block';
            this.listContainer.style.display = 'none';
        } else {
            this.empty.style.display = 'none';
            this.listContainer.style.display = 'block';
        }
        this.reposition();
    }

    renderList() {
        // Limit to 50 items to keep DOM lightweight while appearing "full"
        const limit = 50;
        const items = this.filteredProjects.slice(0, limit);
        const hasMore = this.filteredProjects.length > limit;
        
        let html = '';
        const selectedId = this.hidden.value;
        
        items.forEach((p, i) => {
            const isHighlight = i === this.highlightIndex ? 'highlighted' : '';
            const isSelected = String(p.id) === String(selectedId) ? 'background: var(--primary-light);' : ''; // Use variable for dark mode compatibility
            const progressColor = p.progress >= 100 ? 'var(--success)' : (p.progress > 80 ? 'var(--warning)' : 'var(--info)'); // Use variables
            
            // Standard block layout, no absolute positioning
            html += `
                <div class="vs-item ${isHighlight}" style="${isSelected}" 
                     role="option" aria-selected="${String(p.id) === String(selectedId)}"
                     onmousedown="window.vsSelect(${p.id}, '${this.escape(p.name)}', '${this.escape(p.code)}')">
                    <div style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                        <span class="name" style="font-weight:500;">${this.highlightMatch(p.name, this.input.value)}</span>
                        <span class="code" style="margin-left:8px; color:var(--text-secondary);">${this.highlightMatch(p.code, this.input.value)}</span>
                    </div>
                    <div style="font-size:12px; color:${progressColor}; width:40px; text-align:right;">${p.progress}%</div>
                </div>
            `;
        });
        
        if (hasMore) {
             html += `
                <div style="padding:8px; text-align:center; font-size:12px; color:var(--text-muted); border-top:1px dashed var(--border-color);">
                    结果过多，仅显示前 ${limit} 条 / Showing top ${limit} results
                </div>
             `;
        }
        
        this.listContainer.innerHTML = html;
    }
    
    escape(str) {
        if (!str) return '';
        return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
    }

    highlightMatch(text, q) {
        if (!text) return '';
        if (!q || q.includes('[')) return text;
        try {
            const reg = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
            return text.replace(reg, '<span style="color:var(--primary);font-weight:bold;">$1</span>');
        } catch(e) {
            return text;
        }
    }

    select(id, name, code) {
        this.hidden.value = id;
        this.input.value = `${name} [${code}]`;
        this.close();
        if (window.loadTemplateRecommendations) window.loadTemplateRecommendations();
    }

    onKeydown(e) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            // Max index is displayed items count - 1
            const limit = 50;
            const maxIndex = Math.min(this.filteredProjects.length, limit) - 1;
            this.highlightIndex = Math.min(this.highlightIndex + 1, maxIndex);
            this.renderList();
            this.scrollToHighlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.highlightIndex = Math.max(this.highlightIndex - 1, 0);
            this.renderList();
            this.scrollToHighlight();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (this.highlightIndex >= 0 && this.filteredProjects[this.highlightIndex]) {
                const p = this.filteredProjects[this.highlightIndex];
                this.select(p.id, p.name, p.code);
            }
        }
    }
    
    scrollToHighlight() {
        const highlighted = this.listContainer.querySelector('.vs-item.highlighted');
        if (highlighted) {
            highlighted.scrollIntoView({block: 'nearest', behavior: 'smooth'});
        }
    }
}

// Global helper for event handlers
window.vsSelect = function(id, name, code) {
     if (window.virtualProjectSelect) window.virtualProjectSelect.select(id, name, code);
};
