/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useInputField } from "@web/views/fields/input_field_hook";
import { Component, useRef, onWillUpdateProps, onPatched } from "@odoo/owl";

export class FieldMaskingEbizA extends Component {
    static template = "payment_ebizcharge_crm.FieldMasking"; // Link the template here

    setup() {
        super.setup();

        useInputField({
            getValue: () => this.props.record._initialTextValues.ebiz_security_key || "",
            refName: "inputebizsecurity",
        });

        this.inputRef = useRef("input");
        this.maskSecurityKeyEbiz();

        onWillUpdateProps((nextProps) => this.updateKey(nextProps));
        onPatched(this.maskSecurityKeyEbiz);
    }

    maskSecurityKeyEbiz() {
        const key = this.props.record.data.ebiz_security_key || "";
        if (key) {
            const maskedKey = this.getMaskedKeyEbiz(key);
            this.props.record._initialTextValues.ebiz_security_key = maskedKey;
        }
    }

    getMaskedKeyEbiz(key) {
        const segments = key.match(/.{1,8}/g) || [];
        if (segments.length < 2) return key;
        const [startValue, ...rest] = segments;
        const endValue = rest.pop() || "";
        return `${startValue}_****_***_****_${endValue}`;
    }

    updateKey(nextProps) {
        if (nextProps.record.data.ebiz_security_key) {
            const maskedKey = this.getMaskedKeyEbiz(nextProps.record.data.ebiz_security_key);
            nextProps.record._initialTextValues.ebiz_security_key = maskedKey;
        }
    }
}

// Register the component
registry.category("fields").add("security_field_masking", {
    component: FieldMaskingEbizA, // Register only the component
});