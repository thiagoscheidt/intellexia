(function () {
    function escapeHtml(text) {
        return String(text || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function escapeAttr(text) {
        return escapeHtml(text);
    }

    function normalizeReleaseTimestamp(value) {
        if (value === null || value === undefined || value === '') {
            return null;
        }

        var n = Number(value);
        if (!Number.isFinite(n) || n <= 0) {
            return null;
        }

        if (n > 10000000000) {
            return Math.floor(n / 1000);
        }

        return Math.floor(n);
    }

    function formatReleaseDate(value) {
        var ts = normalizeReleaseTimestamp(value);
        if (!ts) {
            return '-';
        }

        var dt = new Date(ts * 1000);
        if (Number.isNaN(dt.getTime())) {
            return '-';
        }

        return dt.toLocaleDateString('pt-BR');
    }

    function releaseBadgeClass(value) {
        return formatReleaseDate(value) === '-' ? 'release-date-badge release-date-badge--muted' : 'release-date-badge';
    }

    function formatContext(value) {
        var n = Number(value);
        if (!Number.isFinite(n) || n <= 0) {
            return '-';
        }
        return n.toLocaleString('pt-BR') + ' tokens';
    }

    function formatPrice(value) {
        if (value === null || value === undefined || value === '') {
            return '-';
        }

        var n = Number(value);
        if (!Number.isFinite(n)) {
            return String(value);
        }

        return '$' + n + ' / token';
    }

    var providerLabelMap = {
        openai: 'OpenAI',
        anthropic: 'Anthropic',
        google: 'Google',
        meta: 'Meta',
        xai: 'xAI',
        mistralai: 'Mistral',
        deepseek: 'DeepSeek',
        qwen: 'Qwen',
        cohere: 'Cohere',
        perplexity: 'Perplexity',
        moonshotai: 'Moonshot',
        microsoft: 'Microsoft',
        default: 'Padrão',
        other: 'Outros',
    };

    function getProviderLabel(providerKey) {
        return providerLabelMap[providerKey] || providerKey;
    }

    function getProviderKeyFromModel(model) {
        var id = String(model && model.id || '').trim().toLowerCase();
        if (!id) {
            return 'default';
        }

        var namespace = id.indexOf('/') >= 0 ? id.split('/')[0] : id;

        if (namespace.indexOf('openai') >= 0) return 'openai';
        if (namespace.indexOf('anthropic') >= 0) return 'anthropic';
        if (namespace.indexOf('google') >= 0 || namespace.indexOf('gemini') >= 0) return 'google';
        if (namespace.indexOf('meta') >= 0 || namespace.indexOf('llama') >= 0) return 'meta';
        if (namespace.indexOf('x-ai') >= 0 || namespace.indexOf('xai') >= 0 || namespace.indexOf('grok') >= 0) return 'xai';
        if (namespace.indexOf('mistral') >= 0) return 'mistralai';
        if (namespace.indexOf('deepseek') >= 0) return 'deepseek';
        if (namespace.indexOf('qwen') >= 0 || namespace.indexOf('alibaba') >= 0) return 'qwen';
        if (namespace.indexOf('cohere') >= 0) return 'cohere';
        if (namespace.indexOf('perplexity') >= 0) return 'perplexity';
        if (namespace.indexOf('moonshot') >= 0 || namespace.indexOf('kimi') >= 0) return 'moonshotai';
        if (namespace.indexOf('microsoft') >= 0 || namespace.indexOf('azure') >= 0) return 'microsoft';
        return 'other';
    }

    function sortByReleaseDate(models) {
        models.sort(function (a, b) {
            var aDefault = !String(a.id || '').trim();
            var bDefault = !String(b.id || '').trim();
            if (aDefault && !bDefault) return -1;
            if (!aDefault && bDefault) return 1;

            var aTs = normalizeReleaseTimestamp(a.release_timestamp) || 0;
            var bTs = normalizeReleaseTimestamp(b.release_timestamp) || 0;
            if (aTs !== bTs) {
                return bTs - aTs;
            }

            return String(a.name || '').localeCompare(String(b.name || ''), 'pt-BR');
        });
    }

    function ModelPickerModal(options) {
        this.modalId = options.modalId;
        this.defaultModelId = options.defaultModelId || '';
        this.models = Array.isArray(options.models) ? options.models.slice() : [];
        this.onSelect = typeof options.onSelect === 'function' ? options.onSelect : function () { };
        this.getSelectedModelId = typeof options.getSelectedModelId === 'function' ? options.getSelectedModelId : function () { return ''; };

        this.selectedProviderFilter = 'all';

        this.modalEl = document.getElementById(this.modalId);
        if (!this.modalEl) {
            throw new Error('ModelPickerModal: modal não encontrado: ' + this.modalId);
        }

        this.root = this.modalEl.querySelector('[data-model-picker-root]');
        this.searchInput = this.root.querySelector('[data-role="search-input"]');
        this.providerFiltersContainer = this.root.querySelector('[data-role="provider-filters"]');
        this.modelListContainer = this.root.querySelector('[data-role="model-list"]');

        this.bindEvents();
        this.renderProviderFilters();
        this.renderModelList('');
    }

    ModelPickerModal.prototype.bindEvents = function () {
        var self = this;

        if (this.searchInput) {
            this.searchInput.addEventListener('input', function () {
                self.renderModelList(self.searchInput.value || '');
            });
        }

        if (this.providerFiltersContainer) {
            this.providerFiltersContainer.addEventListener('click', function (event) {
                var button = event.target.closest('[data-provider-key]');
                if (!button) return;

                self.selectedProviderFilter = String(button.getAttribute('data-provider-key') || 'all');
                self.renderProviderFilters();
                self.renderModelList(self.searchInput ? self.searchInput.value : '');
            });
        }

        if (this.modelListContainer) {
            this.modelListContainer.addEventListener('click', function (event) {
                var target = event.target.closest('[data-model-id]');
                if (!target) return;

                var modelId = target.getAttribute('data-model-id') || '';
                self.onSelect(modelId, self.getModelById(modelId));
                self.renderModelList(self.searchInput ? self.searchInput.value : '');

                if (window.bootstrap && window.bootstrap.Modal) {
                    window.bootstrap.Modal.getOrCreateInstance(self.modalEl).hide();
                }
            });
        }

        this.modalEl.addEventListener('show.bs.modal', function () {
            self.renderProviderFilters();
            self.renderModelList(self.searchInput ? self.searchInput.value : '');
        });
    };

    ModelPickerModal.prototype.getModelById = function (modelId) {
        var id = String(modelId || '').trim();
        if (!id) return null;
        for (var i = 0; i < this.models.length; i += 1) {
            if (String(this.models[i].id || '').trim() === id) {
                return this.models[i];
            }
        }
        return null;
    };

    ModelPickerModal.prototype.renderProviderFilters = function () {
        if (!this.providerFiltersContainer) return;

        var providerCountMap = {};
        this.models.forEach(function (model) {
            var key = getProviderKeyFromModel(model);
            providerCountMap[key] = (providerCountMap[key] || 0) + 1;
        });

        var providers = Object.keys(providerCountMap).sort(function (a, b) {
            return getProviderLabel(a).localeCompare(getProviderLabel(b), 'pt-BR');
        });

        var items = [{ key: 'all', label: 'Todos', count: this.models.length }]
            .concat(providers.map(function (key) {
                return { key: key, label: getProviderLabel(key), count: providerCountMap[key] || 0 };
            }));

        var selectedFilter = this.selectedProviderFilter;
        this.providerFiltersContainer.innerHTML = items.map(function (item) {
            var active = selectedFilter === item.key;
            return '' +
                '<button type="button" class="btn ' + (active ? 'btn-primary' : 'btn-outline-secondary') + ' provider-filter-chip" ' +
                'data-provider-key="' + escapeAttr(item.key) + '" title="Filtrar por ' + escapeAttr(item.label) + '">' +
                escapeHtml(item.label) + ' <span class="ms-1">(' + item.count + ')</span>' +
                '</button>';
        }).join('');
    };

    ModelPickerModal.prototype.renderModelList = function (filterText) {
        if (!this.modelListContainer) return;

        var filter = String(filterText || '').trim().toLowerCase();
        var selected = String(this.getSelectedModelId() || '').trim();
        var self = this;

        var list = [
            {
                id: '',
                name: 'Padrão do ambiente',
                description: 'Usa FAP_CLASSIFIER_MODEL (' + this.defaultModelId + ').',
                context_length: null,
                prompt_price: null,
                completion_price: null,
                release_timestamp: null,
            }
        ].concat(this.models).filter(function (item) {
            if (self.selectedProviderFilter !== 'all') {
                var modelProvider = getProviderKeyFromModel(item);
                if (modelProvider !== self.selectedProviderFilter) {
                    return false;
                }
            }

            if (!filter) {
                return true;
            }

            var haystack = (String(item.name || '') + ' ' + String(item.id || '') + ' ' + String(item.description || '')).toLowerCase();
            return haystack.indexOf(filter) >= 0;
        });

        sortByReleaseDate(list);

        if (!list.length) {
            this.modelListContainer.innerHTML = '<div class="text-muted small p-2">Nenhum modelo encontrado.</div>';
            return;
        }

        this.modelListContainer.innerHTML = list.map(function (item) {
            var id = String(item.id || '').trim();
            var active = selected === id || (!selected && !id);
            return '' +
                '<button type="button" class="list-group-item list-group-item-action model-item ' + (active ? 'active' : '') + '" data-model-id="' + escapeAttr(id) + '">' +
                '<div class="d-flex justify-content-between align-items-start gap-2">' +
                '<div>' +
                '<div class="fw-semibold">' + escapeHtml(item.name || id || 'Padrão do ambiente') + '</div>' +
                '<div class="model-id">' + escapeHtml(id || ('FAP_CLASSIFIER_MODEL: ' + self.defaultModelId)) + '</div>' +
                '</div>' +
                '<div class="text-end small">' +
                '<div><span class="badge ' + releaseBadgeClass(item.release_timestamp) + '">Lançamento: ' + escapeHtml(formatReleaseDate(item.release_timestamp)) + '</span></div>' +
                '<div>Ctx: ' + escapeHtml(formatContext(item.context_length)) + '</div>' +
                '<div>In: ' + escapeHtml(formatPrice(item.prompt_price)) + '</div>' +
                '<div>Out: ' + escapeHtml(formatPrice(item.completion_price)) + '</div>' +
                '</div>' +
                '</div>' +
                '<div class="small mt-2 ' + (active ? '' : 'text-muted') + '">' + escapeHtml(item.description || '') + '</div>' +
                '</button>';
        }).join('');
    };

    window.ModelPickerModal = ModelPickerModal;
    window.ModelPickerModalUtils = {
        formatReleaseDate: formatReleaseDate,
        releaseBadgeClass: releaseBadgeClass,
        normalizeReleaseTimestamp: normalizeReleaseTimestamp,
    };
})();
