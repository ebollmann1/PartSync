/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

const ConfirmFieldMixin = {
    events: {
        'focus': '_onFocusValue',
        'blur': '_onVerifyMatch',
    },

    start() {
        this.$el.tooltip({
            trigger: 'manual',
            container: 'body',
            placement: 'bottom',
            boundary: 'viewport',
            customClass: 'modern-tooltip-left',
            html: true,
        });
        return this._super(...arguments);
    },

    _onFocusValue() {
        Tooltip.getOrCreateInstance(this.$el).hide();
        this.$el.siblings('.o_invalid_field').remove();
        this.$el.parent('.form-group')
            .removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
        this.$el.parent('.form-group')
            .removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    },

    _onVerifyMatch() {
        const confirmVal = this.$el.val();
        const matchVal = $('#' + this.$el.attr('data-confirm-id')).val();
        const tooltip = Tooltip.getOrCreateInstance(this.$el);
        if (matchVal.length > 0 && confirmVal.length > 0 && confirmVal !== matchVal) {
            this.$el.parent('.form-group')
                .addClass('o_has_error').find('.form-control, .custom-select').addClass('is-invalid');
            this.$el.parent('.form-group')
                .removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
        } else if (confirmVal.length <= 0 || matchVal.length <= 0) {
            tooltip.hide();
        } else {
            tooltip.hide();
            this.$el.siblings('.o_invalid_field').remove();
            this.$el.parent('.form-group')
                .addClass('o_has_success').find('.form-control, .custom-select').addClass('is-valid');
            this.$el.parent('.form-group')
                .removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
        }
    },
};

publicWidget.registry.ConfirmAccountNumber = publicWidget.Widget.extend({
    ...ConfirmFieldMixin,
    selector: '#confirm_account_number',
});

publicWidget.registry.ConfirmRoutingNumber = publicWidget.Widget.extend({
    ...ConfirmFieldMixin,
    selector: '#confirm_routing_number',
});
