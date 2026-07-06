/** @odoo-module **/

import { systrayItem } from "@website/systray_items/edit_website";
import { patch } from "@web/core/utils/patch";

patch(systrayItem.Component.prototype, {
    setup() {
        super.setup();
    },

    startEdit() {
//        if ( this.websiteService.websiteRootInstance.el.querySelector('.o_wsale_filmstip_container')){
//            this.websiteService.websiteRootInstance.el.querySelector('.o_wsale_filmstip_container').classList.toggle("d-none")
//        }
        if (this.websiteService.websiteRootInstance.el.querySelector('.o_wsale_filmstip_container')) {
            const filmstripContainer = this.websiteService.websiteRootInstance.el.querySelector('.o_wsale_filmstip_container');
            const blankDiv = document.createElement('div');
            filmstripContainer.parentNode.replaceChild(blankDiv, filmstripContainer);
        }
        super.startEdit();
    },
});
