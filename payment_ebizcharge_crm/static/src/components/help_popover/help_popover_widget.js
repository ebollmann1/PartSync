/** @odoo-module **/

import { registry } from "@web/core/registry";
import { usePopover } from "@web/core/popover/popover_hook";
import { Component, useState } from "@odoo/owl";
import { localization } from "@web/core/l10n/localization";

class HelpPopover extends Component {}

HelpPopover.template = "payment_ebizcharge_crm.HelpPopOvertemplate";

class HelpPopoverWidget extends Component {
    setup() {
        super.setup();
        const position = localization.direction === "rtl" ? "bottom" : "left";
        this.popover = usePopover(HelpPopover, { position });
    }

    showPopup(ev) {
        console.log("Opening popover...");
        this.popover.open(ev.currentTarget);
    }

    closePopup() {
        console.log("Closing popover...");
        this.popover.close();
    }
}

HelpPopoverWidget.components = { Popover: HelpPopover };
HelpPopoverWidget.template = "payment_ebizcharge_crm.buttonhelp";

registry.category("view_widgets").add("help_popover_widget", {
    component: HelpPopoverWidget,
});