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
        this.pageSize = 30;
        this.projects = [];
        this.page = 1;
        this.hasMore = false;
        this.currentQuery = '';
        this.highlightIndex = -1;
        this.searchDebounce = null;
        this.abortController = null;
        this.isOpen = false;

        if (this.input) {
            this.dropdown.style.display = 'none';
            this.init();
        }
    }

    init() {
        if (this.dropdown.parentElement !== document.body) document.body.appendChild(this.dropdown);
        this.input.addEventListener('focus', () => this.onFocus());
        this.input.addEventListener('blur', () => setTimeout(() => this.close(), 250));
        this.input.addEventListener('input', (event) => this.onInput(event.target.value));
        this.input.addEventListener('keydown', (event) => this.onKeydown(event));
        window.addEventListener('scroll', () => { if (this.isOpen) this.reposition(); }, {passive: true});
        window.addEventListener('resize', () => { if (this.isOpen) this.reposition(); }, {passive: true});
        this.search('', 1);
    }

    async search(query, page = 1, append = false) {
        if (this.abortController) this.abortController.abort();
        this.abortController = new AbortController();
        this.setLoading(true);
        this.currentQuery = query.trim();

        const params = new URLSearchParams({
            q: this.currentQuery,
            page: String(page),
            limit: String(this.pageSize),
            scope: this.scope,
        });
        if (this.hidden.value) params.set('selected_id', this.hidden.value);

        try {
            const response = await fetch(`${this.api}?${params}`, {signal: this.abortController.signal});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            this.projects = append ? this.projects.concat(payload.results || []) : (payload.results || []);
            this.page = payload.pagination?.page || page;
            this.hasMore = Boolean(payload.pagination?.has_more);
            this.highlightIndex = -1;
            this.renderList();
            this.updateDebug(`已加载 ${this.projects.length} 个匹配项目 / ${this.projects.length} matching projects`);
        } catch (error) {
            if (error.name !== 'AbortError') {
                this.projects = [];
                this.hasMore = false;
                this.renderList();
                this.updateDebug(`加载失败 / Load failed: ${error.message}`);
            }
        } finally {
            this.setLoading(false);
        }
    }

    loadMore() {
        if (this.hasMore) this.search(this.currentQuery, this.page + 1, true);
    }

    onInput(value) {
        clearTimeout(this.searchDebounce);
        this.hidden.value = '';
        this.searchDebounce = setTimeout(() => this.search(value, 1), 250);
    }

    onFocus() {
        this.isOpen = true;
        this.dropdown.classList.add('open');
        this.dropdown.style.display = 'block';
        this.reposition();
        if (!this.projects.length) this.search('', 1);
    }

    close() {
        this.isOpen = false;
        this.dropdown.classList.remove('open');
        this.dropdown.style.display = 'none';
    }

    reposition() {
        if (!this.isOpen) return;
        const rect = this.input.getBoundingClientRect();
        if (!rect.width || !rect.height) return this.close();
        Object.assign(this.dropdown.style, {
            position: 'absolute',
            top: `${rect.bottom + window.scrollY + 4}px`,
            left: `${rect.left + window.scrollX}px`,
            width: `${rect.width}px`,
            zIndex: '9999',
            maxHeight: '420px',
            overflowY: 'auto',
        });
    }

    setLoading(active) {
        this.loading.style.display = active ? 'block' : 'none';
        this.listContainer.style.display = active ? 'none' : 'block';
        if (this.indicator) this.indicator.textContent = active ? '...' : '▼';
    }

    updateDebug(message) {
        if (this.debugMsg) {
            this.debugMsg.textContent = message;
            this.debugMsg.style.display = 'block';
        }
    }

    renderList() {
        if (!this.projects.length) {
            this.listContainer.innerHTML = '';
            this.empty.style.display = 'block';
            return;
        }
        this.empty.style.display = 'none';
        const selectedId = this.hidden.value;
        this.listContainer.innerHTML = this.projects.map((project, index) => {
            const highlighted = index === this.highlightIndex ? 'highlighted' : '';
            const selected = String(project.id) === String(selectedId) ? 'background:var(--primary-light);' : '';
            const progress = Number.isFinite(Number(project.progress)) ? Number(project.progress) : 0;
            return `
                <div class="vs-item ${highlighted}" style="${selected}" role="option"
                     aria-selected="${String(project.id) === String(selectedId)}"
                     onmousedown="window.vsSelectById(${project.id})">
                    <div style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                        <span class="name" style="font-weight:500;">${this.highlight(project.name)}</span>
                        <span class="code" style="margin-left:8px;color:var(--text-secondary);">${this.highlight(project.code)}</span>
                    </div>
                    <div style="font-size:12px;color:var(--text-muted);width:44px;text-align:right;">${progress}%</div>
                </div>`;
        }).join('') + (this.hasMore ? `
            <button type="button" class="btn btn-ghost" style="width:100%;margin-top:4px;"
                    onmousedown="event.preventDefault();window.vsLoadMore();">
                加载更多 / Load more
            </button>` : '');
    }

    escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    highlight(value) {
        const text = String(value || '');
        if (!this.currentQuery) return this.escapeHtml(text);
        const escaped = this.currentQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const matcher = new RegExp(`(${escaped})`, 'gi');
        return text.split(matcher).map((part, index) => (
            index % 2
                ? `<span style="color:var(--primary);font-weight:700;">${this.escapeHtml(part)}</span>`
                : this.escapeHtml(part)
        )).join('');
    }

    select(id, name, code) {
        this.hidden.value = id;
        this.input.value = `${name} [${code}]`;
        this.close();
        if (window.loadTemplateRecommendations) window.loadTemplateRecommendations();
    }

    onKeydown(event) {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            this.highlightIndex = Math.min(this.highlightIndex + 1, this.projects.length - 1);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            this.highlightIndex = Math.max(this.highlightIndex - 1, 0);
        } else if (event.key === 'Enter' && this.projects[this.highlightIndex]) {
            event.preventDefault();
            const project = this.projects[this.highlightIndex];
            return this.select(project.id, project.name, project.code);
        } else {
            return;
        }
        this.renderList();
        this.listContainer.querySelector('.highlighted')?.scrollIntoView({block: 'nearest'});
    }
}

window.vsSelect = (id, name, code) => window.virtualProjectSelect?.select(id, name, code);
window.vsSelectById = (id) => {
    const project = window.virtualProjectSelect?.projects.find((item) => item.id === id);
    if (project) window.virtualProjectSelect.select(project.id, project.name, project.code);
};
window.vsLoadMore = () => window.virtualProjectSelect?.loadMore();
