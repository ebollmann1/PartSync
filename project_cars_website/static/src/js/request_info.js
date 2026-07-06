/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';

publicWidget.registry.RequestInfoButton = publicWidget.Widget.extend({
    selector: '.js_request_info_btn',

    events: {
        'click': '_onClickRequestInfo',
    },

    /**
     * Triggered when the "Request Product Information" button is clicked
     */
    _onClickRequestInfo(ev) {
        ev.preventDefault();
        const productId = ev.currentTarget.dataset.product_id;
        const productName = ev.currentTarget.dataset.product_name;
        const returnUrl = ev.currentTarget.dataset.return_url;

        const url = new URL('/get_more_product_information', window.location.origin);
        url.searchParams.set('product_id', productId);
        url.searchParams.set('product_name', productName);
        url.searchParams.set('return_url', returnUrl);

        window.open(url.toString(), '_blank');
    },
});

export const RequestInfoButton = publicWidget.registry.RequestInfoButton;

