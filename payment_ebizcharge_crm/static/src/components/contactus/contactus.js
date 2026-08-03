/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

class ContactUsPage extends Component {
    static template = "payment_ebizcharge_crm.contact_us_page";
}

registry.category("actions").add("contact_us_page", ContactUsPage);
