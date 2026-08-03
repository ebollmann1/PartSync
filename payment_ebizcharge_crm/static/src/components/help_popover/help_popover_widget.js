/** @odoo-module **/

import { registry } from "@web/core/registry";
import { usePopover } from "@web/core/popover/popover_hook";
import { Component } from "@odoo/owl";
import { localization } from "@web/core/l10n/localization";

class HelpPopover extends Component {
    static template = "payment_ebizcharge_crm.HelpPopOvertemplate";
}

class HelpPopoverWidget extends Component {
    static components = { Popover: HelpPopover };
    static template = "payment_ebizcharge_crm.buttonhelp";

    setup() {
        const position = localization.direction === "rtl" ? "bottom" : "left";
        this.popover = usePopover(HelpPopover, { position });
    }

    showPopup(ev) {
        this.popover.open(ev.currentTarget);
    }

    closePopup() {
        this.popover.close();
    }
}

registry.category("view_widgets").add("help_popover_widget", {
    component: HelpPopoverWidget,
});
