/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useInputField } from "@web/views/fields/input_field_hook";
import { Component, useRef, onWillUpdateProps, onPatched } from "@odoo/owl";

export class FieldMaskingEbizDevice extends Component {
    static template = "payment_ebizcharge_crm.FieldMaskingDevice"; // Link the template here

    setup() {
        super.setup();

        useInputField({
            getValue: () => this.props.record._initialTextValues.emv_device_key || "",
            refName: "inputdate",
        });

        this.inputRef = useRef("input");
        this.maskSecurityKey();

        onWillUpdateProps((nextProps) => this.updateKey(nextProps));
        onPatched(this.maskSecurityKey);
    }

    maskSecurityKey() {
        const key = this.props.record.data.emv_device_key || "";
        if (key) {
            const maskedKey = this.getMaskedKey(key);
            this.props.record._initialTextValues.emv_device_key = maskedKey;
        }
    }

    getMaskedKey(key) {
        const segments = key.match(/.{1,8}/g) || [];
        if (segments.length < 2) return key;
        const [startValue, ...rest] = segments;
        const endValue = rest.pop() || "";
        return `${startValue}_****_***_****_${endValue}`;
    }

    updateKey(nextProps) {
        if (nextProps.record.data.emv_device_key) {
            const maskedKey = this.getMaskedKey(nextProps.record.data.emv_device_key);
            nextProps.record._initialTextValues.emv_device_key = maskedKey;
        }
    }
}

// Register the component
registry.category("fields").add("eb_deviceaa_field_masking", {
    component: FieldMaskingEbizDevice, // Register only the component
});