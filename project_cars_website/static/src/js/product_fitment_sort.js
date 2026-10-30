///** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { WebsiteSale } from '@website_sale/interactions/website_sale';
import { PriceRange } from '@website_sale/interactions/price_range';
import { rpc } from "@web/core/network/rpc";
import { renderToFragment } from "@web/core/utils/render";


patch(WebsiteSale.prototype, {

    setup() {
        super.setup();
        this.bindEvents();
    },
    bindEvents() {
        $(document).on('click', '.search_category', this.onSearchCategory.bind(this));
        $(document).on('click', '.search_category_by_name', this.onSearchCategoryByName.bind(this));
        $(document).on('click', '.category_list', this.onClickCategoryList.bind(this));
//        $(document).on('click', '.category_modal_close', this.onClickModalClose.bind(this));
        $(document).on('change', 'select[name="fitment_make"], select[name="fitment_model"], select[name="fitment_year"], select[name="fitment_submodel"], select[name="fitment_rear_wheels"], select[name="vehicle_platform_id"]', this.onChangeFitmentFilter.bind(this));
        $(document).on('click', '.js_mobile_apply_filters', this.onApplyMobileFilters.bind(this));
        $(document).on('change', 'select[name="user_vehicles"]', this.onChangeVehicleInformation.bind(this));
        $(document).find('div#fitment_data_div table').tablesort().data('tablesort')
    },

    onChangeAttribute(ev) {
        if (ev.currentTarget.closest('#o_wsale_offcanvas')) {
            // The offcanvas selections are applied together by Apply Filters.
            return;
        }
        return super.onChangeAttribute(ev);
    },

    async onChangeFitmentFilter(ev) {
        if (ev.target.closest('#o_wsale_offcanvas')) {
            return this.onChangeMobileFitmentFilter(ev);
        }
        const form = ev.target.closest('form') || document.createElement('form');
        form.action = '/shop';
        form.method = 'GET';

        // Get all fitment values
        const params = new URLSearchParams(window.location.search);

        const scope = ev.target.closest('#o_wsale_offcanvas, #products_grid_before') || document;
        scope.querySelectorAll('[name^="fitment_"], [name="vehicle_platform_id"]').forEach(select => {
            if (select.value) {
                params.set(select.name, select.value);
            } else {
                params.delete(select.name);
            }
        });

        window.location.href = `/shop?${params.toString()}`;
    },

    async onChangeMobileFitmentFilter(ev) {
        const offcanvas = ev.target.closest('#o_wsale_offcanvas');
        const fields = [...offcanvas.querySelectorAll(
            'select[name^="fitment_"], select[name="vehicle_platform_id"]'
        )];
        const changedName = ev.target.name;
        if (changedName === 'fitment_make' || changedName === 'fitment_model') {
            for (const field of fields) {
                if (field.name !== 'fitment_make' &&
                    (changedName === 'fitment_make' || field.name !== 'fitment_model')) {
                    field.value = '';
                }
            }
        }
        const selections = Object.fromEntries(fields.map(field => [field.name, field.value]));
        const requestId = this.mobileFitmentRequestId = (this.mobileFitmentRequestId || 0) + 1;
        for (const field of fields) {
            if (field.name !== 'fitment_make') {
                field.disabled = true;
            }
        }
        try {
            const options = await rpc('/shop/fitment/options', {selections});
            if (requestId !== this.mobileFitmentRequestId) {
                return;
            }
            for (const field of fields) {
                if (field.name === 'fitment_make') {
                    continue;
                }
                const values = options[field.name] || [];
                const previousValue = selections[field.name];
                field.replaceChildren(new Option('', ''), ...values.map(value => new Option(value, value)));
                field.value = values.includes(previousValue) ? previousValue : '';
                field.disabled = !selections.fitment_make || !values.length;
            }
        } catch {
            // Keep the current Make selection and let the visitor apply it.
            for (const field of fields) {
                if (field.name !== 'fitment_make') {
                    field.disabled = !selections.fitment_make;
                }
            }
        }
    },

    onApplyMobileFilters(ev) {
        const offcanvas = ev.currentTarget.closest('#o_wsale_offcanvas');
        const params = new URLSearchParams(window.location.search);
        offcanvas.querySelectorAll('[name^="fitment_"], [name="vehicle_platform_id"]').forEach(field => {
            if (field.value) {
                params.set(field.name, field.value);
            } else {
                params.delete(field.name);
            }
        });
        params.delete('attribute_values');
        params.delete('tags');
        const attributes = new Map();
        const tags = new Set();
        offcanvas.querySelectorAll('input:checked, select[name="attribute_value"], select[name="tags"]').forEach(field => {
            if (!field.value) {
                return;
            }
            if (field.name === 'attribute_value') {
                const [attributeId, valueId] = field.value.split('-');
                const values = attributes.get(attributeId) || new Set();
                values.add(valueId);
                attributes.set(attributeId, values);
            } else if (field.name === 'tags') {
                tags.add(field.value);
            }
        });
        for (const [attributeId, values] of attributes) {
            params.append('attribute_values', `${attributeId}-${[...values].join(',')}`);
        }
        if (tags.size) {
            params.set('tags', [...tags].join(','));
        }
        const range = offcanvas.querySelector('#o_wsale_price_range_option input[type="range"]');
        if (range) {
            params.delete('min_price');
            params.delete('max_price');
            if (Number(range.valueLow) !== Number(range.min)) {
                params.set('min_price', range.valueLow);
            }
            if (Number(range.valueHigh) !== Number(range.max)) {
                params.set('max_price', range.valueHigh);
            }
        }
        window.location.href = `/shop?${params.toString()}`;
    },

    async onChangeVehicleInformation(ev) {
        const select = ev.target;
        const selectedValue = select.value;

        // Get current URL params
        const params = new URLSearchParams(window.location.search);

        // Update user_vehicles parameter
        if (selectedValue) {
            params.set('user_vehicles', selectedValue);
        } else {
            params.delete('user_vehicles');
        }

        // Redirect to the new URL
        window.location.href = `/shop?${params.toString()}`;
    },

    async onSearchCategory(ev) {
        if($('.category_backend_modal .modal-body .category_table').length > 0){
            $('.category_backend_modal .modal-body .category_table').remove();
        }
        if($('.category_backend_modal .modal-body .category_table').length === 0){
            $('.category_backend_modal .modal-body #category_search_bar').remove();
            $('.category_backend_modal .modal-body .search_category_by_name').remove();
            $('.category_backend_modal .modal-body #for_numrows').remove();
            $('.category_backend_modal .modal-body #pagesControllers').remove();

            const result = await rpc("/get/product_categories", {});
            var $categoriesTable = $(renderToFragment('project_cars_enhancement.WebsiteCategoryList', {
                categories: result[0],
                search_bar_value: result[1],
            }));
            $('.category_backend_modal .modal-body').append($categoriesTable);
            $('.category_table.tablemanager').tablemanager({
                appendFilterby: false,
                vocabulary: {
                    voc_filter_by: 'Filter By',
                    voc_type_here_filter: 'Filter...',
                    voc_show_rows: 'Rows Per Page'
                },
                pagination: true,
                showrows: [100],
            });

            $('.search_category').click(function(){
                var search_value = $('input#category_search_bar').val();
                if(search_value.length >= 3){
                    $('.category_table').remove();
                }
            });
        }
        $('.category_backend_modal').modal('toggle');
    },

    async onSearchCategoryByName(ev){
        var search_value = $('input#category_search_bar').val();
        let result;
        if(search_value.length >= 3){
            result = await rpc("/get/product_categories", { search_categ_name: search_value });
        } else {
            result = await rpc("/get/product_categories", {});
        }

        $('.category_backend_modal .modal-body').empty();
        var $categoriesTable = $(renderToFragment('project_cars_enhancement.WebsiteCategoryList', {
            categories: result[0],
            search_bar_value: result[1],
        }));
        $('.category_backend_modal .modal-body').append($categoriesTable);
        $('.category_table.tablemanager').tablemanager({
            appendFilterby: false,
            vocabulary: {
                voc_filter_by: 'Filter By',
                voc_type_here_filter: 'Filter...',
                voc_show_rows: 'Rows Per Page'
            },
            pagination: true,
            showrows: [100],
        });
    },

    onClickCategoryList(ev){
        var url = $(ev.currentTarget).attr('url');
        window.location.href = url;
    },

//    onClickModalClose(ev) {
//        $('.category_backend_modal').modal('hide');
//    },
});

patch(PriceRange.prototype, {
    onPriceRangeSelected(ev) {
        if (ev.currentTarget.closest('#o_wsale_offcanvas')) {
            // Let Apply Filters submit the chosen price range with all other filters.
            return;
        }
        return super.onPriceRangeSelected(ev);
    },
});
